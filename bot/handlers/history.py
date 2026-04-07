import json
import logging
from datetime import date, timedelta

from aiogram import Bot, Router
from aiogram.enums import ChatAction
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import today_local
from bot.constants import GOAL_TYPE_LABELS
from bot.handlers.callbacks import _send_daily_ai_analysis
from bot.models.user import User
from bot.services.nutrition import parse_ai_response
from bot.services.prompts import render_prompt
from bot.services.stats import (
    get_today_meals,
    get_today_totals,
    get_period_stats,
    get_period_meals_for_prompt,
)
from bot.services.meal_plan import get_plan_day, get_plan_for_period, compare_day, compare_period
from bot.services.vision.base import VisionProvider
from bot.utils.charts import generate_trend_chart
from bot.utils.formatters import format_macros, format_progress_bar, format_signal

logger = logging.getLogger(__name__)

router = Router()

WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]

# "за неделю", "за месяц" - винительный падеж
PERIOD_LABEL_ACC = {
    "Неделя": "неделю",
    "Месяц": "месяц",
    "Все время": "все время",
}


def _period_za(label: str) -> str:
    """'Неделя' -> 'за неделю'."""
    return f"за {PERIOD_LABEL_ACC.get(label, label.lower())}"


# --- /today ---

@router.message(Command("today"))
async def cmd_today(
    message: Message,
    bot: Bot,
    session: AsyncSession,
    user: User,
    vision_provider: VisionProvider,
    text_provider: VisionProvider | None = None,
):
    totals = await get_today_totals(session, user.id)
    meals = await get_today_meals(session, user.id)

    # --- Quick stats (instant) ---
    today = today_local()
    lines = [f"<b>Сегодня ({today.strftime('%d.%m.%Y')}):</b>\n"]

    if meals:
        lines.append("<b>Приемы пищи:</b>")
        for m in meals:
            time_str = m.logged_at.strftime("%H:%M")
            desc = m.ai_description
            if desc:
                try:
                    desc = json.loads(desc).get("description", "")
                except Exception:
                    desc = ""
            desc = desc or "Прием пищи"
            lines.append(f"{time_str} - {desc} ({m.total_calories:.0f} ккал)")
        lines.append("")

    lines.append("<b>Итого:</b>")
    lines.append(f"Калории: {totals['calories']:.0f} / {user.daily_calories_goal} ккал")
    lines.append(f"Белки: {totals['protein']:.0f} / {user.daily_protein_goal} г")
    lines.append(f"Жиры: {totals['fat']:.0f} / {user.daily_fat_goal} г")
    lines.append(f"Углеводы: {totals['carbs']:.0f} / {user.daily_carbs_goal} г")
    lines.append("")
    lines.append(format_progress_bar(totals["calories"], user.daily_calories_goal))

    # --- plan comparison ---
    plan_day = await get_plan_day(session, user.id)
    plan_comparison = None
    if plan_day and meals:
        plan_comparison = compare_day(plan_day, totals)
        d = plan_comparison["diff"]
        p = plan_comparison["planned"]
        if plan_comparison["overall_matched"]:
            lines.append(f"\n\u2705 <b>Ты в рамках плана!</b> Все показатели +-10%")
        else:
            lines.append(f"\n\U0001f4cb <b>План на сегодня:</b> {int(p['calories'])} ккал "
                         f"(\U0001f4aa {int(p['protein'])} / \U0001f9c8 {int(p['fat'])} / \U0001f33e {int(p['carbs'])})")
            diff_parts = []
            for label, key in [("ккал", "calories"), ("Б", "protein"), ("Ж", "fat"), ("У", "carbs")]:
                v = d[key]
                sign = "+" if v > 0 else ""
                diff_parts.append(f"{label}:{sign}{int(v)}")
            lines.append(f"Отклонение: {' | '.join(diff_parts)}")

    if not meals:
        lines.append("\nПока нет сохраненных приемов пищи.")
        await message.answer("\n".join(lines), parse_mode="HTML")
        return

    await message.answer("\n".join(lines), parse_mode="HTML")

    # --- AI analysis (auto, after stats) ---
    provider = text_provider or vision_provider
    await _send_daily_ai_analysis(message.chat.id, bot, session, user, provider)


# --- shared period report helper ---

async def _send_period_report(
    message: Message,
    bot: Bot,
    session: AsyncSession,
    user: User,
    vision_provider: VisionProvider,
    days: int,
    period_label: str,
):
    """Generate and send a full period report: chart + daily breakdown + AI analysis."""
    stats = await get_period_stats(session, user.id, days=days)

    if stats["days_tracked"] == 0:
        await message.answer(f"Нет данных {_period_za(period_label)}.")
        return

    await bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)

    # date range
    date_from = (today_local() - timedelta(days=days - 1)).strftime("%d.%m")
    date_to = today_local().strftime("%d.%m")
    date_range = f"{date_from} - {date_to}"

    meals, frequent = await get_period_meals_for_prompt(session, user.id, days=days)

    # --- chart ---
    try:
        chart_data = [
            {"day": d["day"], "calories": d["calories"], "protein": d.get("protein", 0)}
            for d in stats["daily_breakdown"]
        ]
        chart_png = generate_trend_chart(chart_data, user.daily_calories_goal, period_label)
        await message.answer_photo(BufferedInputFile(chart_png, filename="trend.png"))
    except Exception:
        logger.exception("Chart generation failed")

    # --- daily breakdown text ---
    breakdown_lines = [f"<b>{period_label} ({date_range}):</b>\n"]

    for d in stats["daily_breakdown"]:
        day = d["day"]
        if hasattr(day, "strftime"):
            wd = WEEKDAYS[day.weekday()]
            day_str = day.strftime("%d.%m")
        else:
            wd = ""
            day_str = str(day)

        cal = d["calories"]
        over = cal > user.daily_calories_goal
        cal_icon = "\u26a0\ufe0f" if over else "\u2705"
        breakdown_lines.append(
            f"{cal_icon} <b>{wd} {day_str}</b>: {cal:.0f} ккал "
            f"(\U0001f4aa {d['protein']:.0f} / \U0001f9c8 {d['fat']:.0f} / \U0001f33e {d['carbs']:.0f})"
        )

    breakdown_lines.append("")
    breakdown_lines.append(f"<b>Среднее в день:</b>")
    breakdown_lines.append(format_macros(
        stats["avg_calories"], stats["avg_protein"],
        stats["avg_fat"], stats["avg_carbs"],
    ))

    cal_pct = int(stats["avg_calories"] / user.daily_calories_goal * 100) if user.daily_calories_goal else 0
    breakdown_lines.append(f"\nСреднее от цели: {cal_pct}%")
    breakdown_lines.append(format_progress_bar(stats["avg_calories"], user.daily_calories_goal))
    breakdown_lines.append(f"Дней отслежено: {stats['days_tracked']}")

    # --- plan comparison ---
    date_from = today_local() - timedelta(days=days - 1)
    date_to = today_local()
    plan_days = await get_plan_for_period(session, user.id, date_from, date_to)
    period_plan_comparison = compare_period(plan_days, stats["daily_breakdown"]) if plan_days else None

    if period_plan_comparison:
        pc = period_plan_comparison
        ad = pc["avg_diff"]
        breakdown_lines.append("")
        breakdown_lines.append(f"\U0001f4cb <b>Соблюдение плана:</b>")
        breakdown_lines.append(f"  Дней с планом: {pc['days_with_data']} / {pc['total_days']}")
        breakdown_lines.append(f"  Дней в рамках (+-10%): {pc['days_matched']} / {pc['days_with_data']}")
        diff_parts = []
        for label, key in [("ккал", "calories"), ("Б", "protein"), ("Ж", "fat"), ("У", "carbs")]:
            v = ad[key]
            sign = "+" if v > 0 else ""
            diff_parts.append(f"{label}:{sign}{int(v)}")
        breakdown_lines.append(f"  Среднее отклонение: {' | '.join(diff_parts)}")
        breakdown_lines.append(f"  Приверженность: {pc['adherence_pct']}%")

    await message.answer("\n".join(breakdown_lines), parse_mode="HTML")

    # --- AI analysis ---
    await bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)

    user_profile = {
        "goal_type": GOAL_TYPE_LABELS.get(user.goal_type, user.goal_type),
        "weight": user.weight,
        "target_weight": user.target_weight,
        "height": user.height,
        "goal_deadline": user.goal_deadline.strftime("%d.%m.%Y") if user.goal_deadline else None,
    }
    user_goals = {
        "calories": user.daily_calories_goal,
        "protein": user.daily_protein_goal,
        "fat": user.daily_fat_goal,
        "carbs": user.daily_carbs_goal,
    }
    prompt_stats = {
        "days_tracked": stats["days_tracked"],
        "avg_calories": int(stats["avg_calories"]),
        "avg_protein": int(stats["avg_protein"]),
        "avg_fat": int(stats["avg_fat"]),
        "avg_carbs": int(stats["avg_carbs"]),
        "daily_breakdown": [
            {
                "day": d["day"].strftime("%d.%m") if hasattr(d["day"], "strftime") else str(d["day"]),
                "calories": int(d["calories"]),
                "protein": int(d["protein"]),
                "fat": int(d["fat"]),
                "carbs": int(d["carbs"]),
            }
            for d in stats["daily_breakdown"]
        ],
    }

    prompt = render_prompt(
        "period_report.j2",
        period_label=period_label,
        user_profile=user_profile,
        user_goals=user_goals,
        stats=prompt_stats,
        frequent_products=frequent,
        plan_comparison=period_plan_comparison,
    )

    try:
        raw = await vision_provider.analyze(None, prompt)
        parsed = parse_ai_response(raw)
    except Exception:
        logger.exception("Period AI analysis failed")
        await message.answer("Не удалось сгенерировать AI-анализ.")
        return

    # --- format AI response ---
    lines = [f"\U0001f4ca <b>AI-анализ {_period_za(period_label)} ({date_range})</b>\n"]

    summary = parsed.get("summary")
    if summary:
        lines.append(summary)

    trend = parsed.get("trend")
    if trend:
        if isinstance(trend, dict):
            direction_icons = {"up": "\u2b06\ufe0f", "down": "\u2b07\ufe0f", "stable": "\u27a1\ufe0f"}
            icon = direction_icons.get(trend.get("direction", ""), "\u2753")
            lines.append(f"\n{icon} <b>Тренд:</b> {trend.get('description', '')}")
        else:
            lines.append(f"\n<b>Тренд:</b> {trend}")

    avg_vs = parsed.get("avg_vs_goal")
    if avg_vs:
        comment = avg_vs.get("comment", "")
        if comment:
            lines.append(f"\n\U0001f3af <b>Среднее vs цель:</b> {comment}")

    patterns = parsed.get("patterns", [])
    if patterns:
        lines.append("\n\U0001f50d <b>Паттерны:</b>")
        for p in patterns:
            lines.append(f"  \u2022 {p}")

    enemies = parsed.get("hidden_enemies", [])
    if enemies:
        lines.append(f"\n\u26a0\ufe0f <b>Скрытые враги:</b>")
        for e in enemies:
            lines.append(
                f"  \u2022 <b>{e.get('product', '?')}</b> ({e.get('frequency', '')}): {e.get('effect', '')}"
            )

    goal_progress = parsed.get("goal_progress")
    if goal_progress:
        lines.append(f"\n\U0001f4c8 <b>Прогресс:</b> {goal_progress}")

    signals = parsed.get("signals", [])
    if signals:
        lines.append("")
        for s in signals:
            lines.append(format_signal(s.get("level", "green"), s.get("text", "")))

    fixes = parsed.get("fixes", [])
    if fixes:
        lines.append(f"\n\U0001f527 <b>Рекомендации:</b>")
        for f in fixes:
            lines.append(f"  \u2022 {f.get('action', '?')}: {f.get('effect', '')}")

    score = parsed.get("score")
    score_comment = parsed.get("score_comment", "")
    if score is not None:
        bar_filled = int(score / 10)
        bar = "\u25fc" * bar_filled + "\u25fb" * (10 - bar_filled)
        lines.append(f"\n{bar} <b>{score}%</b>")
        if score_comment:
            lines.append(score_comment)

    verdict = parsed.get("final_verdict")
    if verdict:
        lines.append(f"\n\U0001f4ac <b>Итог:</b> {verdict}")

    text = "\n".join(lines)

    menu_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="Составить меню на неделю",
            callback_data=f"weekmenu:{days}",
        )]
    ])

    try:
        if len(text) <= 4096:
            await message.answer(text, parse_mode="HTML", reply_markup=menu_kb)
        else:
            parts = text.split("\n\n")
            chunk = ""
            for part in parts:
                if len(chunk) + len(part) + 2 > 4096:
                    await message.answer(chunk, parse_mode="HTML")
                    chunk = part
                else:
                    chunk = chunk + "\n\n" + part if chunk else part
            if chunk:
                await message.answer(chunk, parse_mode="HTML", reply_markup=menu_kb)
    except Exception:
        logger.exception("Failed to send period report")
        await message.answer("Ошибка отправки отчета.")


# --- /history ---

@router.message(Command("history"))
async def cmd_history(
    message: Message,
    bot: Bot,
    session: AsyncSession,
    user: User,
    vision_provider: VisionProvider,
):
    await _send_period_report(message, bot, session, user, vision_provider, days=7, period_label="Неделя")


# --- /stats ---

@router.message(Command("stats"))
async def cmd_stats(
    message: Message,
    bot: Bot,
    session: AsyncSession,
    user: User,
    vision_provider: VisionProvider,
):
    await _send_period_report(message, bot, session, user, vision_provider, days=30, period_label="Месяц")
