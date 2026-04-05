import json
import logging

from aiogram import Bot, Router
from aiogram.enums import ChatAction
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.constants import GOAL_TYPE_LABELS
from bot.models.user import User
from bot.services.nutrition import parse_ai_response
from bot.services.prompts import render_prompt
from bot.services.stats import (
    get_today_meals,
    get_today_totals,
    get_weekly_stats,
    format_today_meals_for_prompt,
)
from bot.services.vision.base import VisionProvider
from bot.utils.formatters import format_macros, format_progress_bar

logger = logging.getLogger(__name__)

router = Router()

WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


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
    lines = ["<b>Сегодня:</b>\n"]

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

    if not meals:
        lines.append("\nПока нет сохраненных приемов пищи.")
        await message.answer("\n".join(lines), parse_mode="HTML")
        return

    await message.answer("\n".join(lines), parse_mode="HTML")

    # --- AI analysis (auto, after stats) ---
    await bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)

    provider = text_provider or vision_provider

    meals_for_prompt = format_today_meals_for_prompt(meals)
    user_profile = {
        "goal_type": GOAL_TYPE_LABELS.get(user.goal_type, user.goal_type),
        "weight": user.weight,
        "target_weight": user.target_weight,
        "height": user.height,
        "activity": user.activity_level or user.activity_description,
    }
    user_goals = {
        "calories": user.daily_calories_goal,
        "protein": user.daily_protein_goal,
        "fat": user.daily_fat_goal,
        "carbs": user.daily_carbs_goal,
    }

    prompt = render_prompt(
        "daily_summary.j2",
        user_profile=user_profile,
        user_goals=user_goals,
        meals=meals_for_prompt,
        day_totals=totals,
    )

    try:
        raw = await provider.analyze(None, prompt)
        parsed = parse_ai_response(raw)
    except Exception:
        logger.exception("Daily AI analysis failed")
        return

    # --- Format AI response ---
    ai_lines = ["\U0001f4ca <b>AI-анализ дня</b>\n"]

    meals_summary = parsed.get("meals_summary", [])
    if meals_summary:
        for ms in meals_summary:
            ai_lines.append(
                f"\U0001f37d <b>{ms.get('name', '?')}</b>: {ms.get('items', '')}"
            )
            ai_lines.append(f"   ~{ms.get('calories', 0)} ккал / {ms.get('protein', 0)}г белка")
        ai_lines.append("")

    t = parsed.get("totals", {})
    if t:
        cal = t.get("calories", 0)
        cal_goal = t.get("calories_goal", user.daily_calories_goal)
        cal_diff = t.get("calories_diff", cal - cal_goal)
        diff_sign = "+" if cal_diff > 0 else ""
        ai_lines.append(f"\U0001f525 <b>Итого: {cal} ккал</b> (цель {cal_goal}, {diff_sign}{cal_diff})")
        ai_lines.append(
            f"\U0001f4aa Б:{t.get('protein', 0)}г  "
            f"\U0001f9c8 Ж:{t.get('fat', 0)}г  "
            f"\U0001f33e У:{t.get('carbs', 0)}г"
        )

    plus = parsed.get("analysis_plus", [])
    if plus:
        ai_lines.append(f"\n\u2705 <b>Плюсы:</b>")
        for p in plus:
            ai_lines.append(f"  \u2022 {p}")

    minus = parsed.get("analysis_minus", [])
    if minus:
        ai_lines.append(f"\n\u274c <b>Проблемы:</b>")
        for m in minus:
            ai_lines.append(f"  \u2022 {m}")

    enemies = parsed.get("hidden_enemies", [])
    if enemies:
        ai_lines.append(f"\n\u26a0\ufe0f <b>Скрытые враги:</b>")
        for e in enemies:
            ai_lines.append(f"  \u2022 <b>{e.get('product', '?')}</b> - {e.get('problem', '')}")

    fixes = parsed.get("fixes", [])
    if fixes:
        ai_lines.append(f"\n\U0001f527 <b>Как сделать идеально:</b>")
        for f in fixes:
            ai_lines.append(f"  \u2022 {f.get('replace', '?')} \u2192 {f.get('with', '?')}: {f.get('effect', '')}")

    after = parsed.get("after_fixes", {})
    if after:
        ai_lines.append(f"\n\u2728 <b>После замен:</b> ~{after.get('calories', '?')} ккал, "
                         f"Б:{after.get('protein', '?')}г - {after.get('verdict', '')}")

    score = parsed.get("score")
    score_comment = parsed.get("score_comment", "")
    if score is not None:
        bar_filled = int(score / 10)
        bar = "\u25fc" * bar_filled + "\u25fb" * (10 - bar_filled)
        ai_lines.append(f"\n{bar} <b>{score}%</b>")
        if score_comment:
            ai_lines.append(score_comment)

    verdict = parsed.get("final_verdict")
    if verdict:
        ai_lines.append(f"\n\U0001f4ac <b>Итог:</b> {verdict}")

    ai_text = "\n".join(ai_lines)

    try:
        if len(ai_text) <= 4096:
            await message.answer(ai_text, parse_mode="HTML")
        else:
            parts = ai_text.split("\n\n")
            chunk = ""
            for part in parts:
                if len(chunk) + len(part) + 2 > 4096:
                    await message.answer(chunk, parse_mode="HTML")
                    chunk = part
                else:
                    chunk = chunk + "\n\n" + part if chunk else part
            if chunk:
                await message.answer(chunk, parse_mode="HTML")
    except Exception:
        logger.exception("Failed to send daily AI analysis")


@router.message(Command("history"))
async def cmd_history(message: Message, session: AsyncSession, user: User):
    stats = await get_weekly_stats(session, user.id)

    if stats["days_tracked"] == 0:
        await message.answer("Нет данных за последние 7 дней.")
        return

    lines = ["<b>История за 7 дней:</b>\n"]

    for day_data in stats["daily_breakdown"]:
        day = day_data["day"]
        if hasattr(day, "strftime"):
            day_str = day.strftime("%d.%m")
            wd = WEEKDAYS[day.weekday()]
        else:
            day_str = str(day)
            wd = ""
        cal = day_data["calories"]
        lines.append(f"{wd} {day_str}: {cal:.0f} ккал")

    lines.append(f"\nДней с данными: {stats['days_tracked']}")

    await message.answer("\n".join(lines), parse_mode="HTML")


@router.message(Command("stats"))
async def cmd_stats(message: Message, session: AsyncSession, user: User):
    stats = await get_weekly_stats(session, user.id)

    if stats["days_tracked"] == 0:
        await message.answer("Нет данных для статистики.")
        return

    lines = ["<b>Статистика за 7 дней:</b>\n"]
    lines.append("<b>Среднее в день:</b>")
    lines.append(format_macros(
        stats["avg_calories"], stats["avg_protein"],
        stats["avg_fat"], stats["avg_carbs"],
    ))
    lines.append(f"\nДней отслежено: {stats['days_tracked']}")

    cal_pct = int(stats["avg_calories"] / user.daily_calories_goal * 100) if user.daily_calories_goal else 0
    lines.append(f"Среднее от цели по калориям: {cal_pct}%")

    await message.answer("\n".join(lines), parse_mode="HTML")
