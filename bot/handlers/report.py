import json
import logging

from aiogram import Router, F
from aiogram.enums import ChatAction
from aiogram.filters import Command
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy.ext.asyncio import AsyncSession

from bot.constants import GOAL_TYPE_LABELS
from bot.models.user import User
from bot.services.nutrition import parse_ai_response
from bot.services.prompts import render_prompt
from bot.services.stats import get_period_stats, get_period_meals_for_prompt
from bot.services.vision.base import VisionProvider
from bot.utils.charts import generate_trend_chart
from bot.utils.formatters import format_signal

logger = logging.getLogger(__name__)

router = Router()

PERIODS = {
    "7": ("Неделя", 7),
    "30": ("Месяц", 30),
    "all": ("Все время", 365),
}


@router.message(Command("report"))
async def cmd_report(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Неделя", callback_data="report:7"),
            InlineKeyboardButton(text="Месяц", callback_data="report:30"),
            InlineKeyboardButton(text="Все время", callback_data="report:all"),
        ]
    ])
    await message.answer(
        "<b>AI-анализ питания за период</b>\n\nВыберите период:",
        reply_markup=kb,
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("report:"))
async def cb_report(
    callback: CallbackQuery,
    session: AsyncSession,
    user: User,
    vision_provider: VisionProvider,
):
    period_key = callback.data.split(":")[1]
    if period_key not in PERIODS:
        await callback.answer("Неизвестный период")
        return

    period_label, days = PERIODS[period_key]
    await callback.answer(f"Генерирую отчет за {period_label.lower()}...")
    await callback.bot.send_chat_action(chat_id=callback.message.chat.id, action=ChatAction.TYPING)

    stats = await get_period_stats(session, user.id, days=days)
    if stats["days_tracked"] == 0:
        await callback.message.answer("Нет данных за этот период.")
        return

    meals, frequent = await get_period_meals_for_prompt(session, user.id, days=days)

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
    )

    try:
        raw = await vision_provider.analyze(None, prompt)
        parsed = parse_ai_response(raw)
    except Exception:
        logger.exception("Report generation failed")
        await callback.message.answer("Не удалось сгенерировать отчет. Попробуйте позже.")
        return

    # --- Send chart ---
    try:
        chart_data = [
            {
                "day": d["day"],
                "calories": d["calories"],
                "protein": d.get("protein", 0),
            }
            for d in stats["daily_breakdown"]
        ]
        chart_png = generate_trend_chart(
            chart_data, user.daily_calories_goal, period_label
        )
        photo = BufferedInputFile(chart_png, filename="trend.png")
        await callback.message.answer_photo(photo)
    except Exception:
        logger.exception("Chart generation failed")

    # --- Format text response ---
    lines = [f"\U0001f4ca <b>Отчет за {period_label.lower()}</b>\n"]

    summary = parsed.get("summary")
    if summary:
        lines.append(summary)

    # Trend
    trend = parsed.get("trend")
    if trend:
        if isinstance(trend, dict):
            direction_icons = {"up": "\u2b06\ufe0f", "down": "\u2b07\ufe0f", "stable": "\u27a1\ufe0f"}
            icon = direction_icons.get(trend.get("direction", ""), "\u2753")
            lines.append(f"\n{icon} <b>Тренд:</b> {trend.get('description', '')}")
        else:
            lines.append(f"\n<b>Тренд:</b> {trend}")

    # Avg vs goal
    avg_vs = parsed.get("avg_vs_goal")
    if avg_vs:
        comment = avg_vs.get("comment", "")
        if comment:
            lines.append(f"\n\U0001f3af <b>Среднее vs цель:</b> {comment}")

    # Patterns
    patterns = parsed.get("patterns", [])
    if patterns:
        lines.append("\n\U0001f50d <b>Паттерны:</b>")
        for p in patterns:
            lines.append(f"  \u2022 {p}")

    # Hidden enemies
    enemies = parsed.get("hidden_enemies", [])
    if enemies:
        lines.append(f"\n\u26a0\ufe0f <b>Скрытые враги:</b>")
        for e in enemies:
            product = e.get("product", "?")
            freq = e.get("frequency", "")
            effect = e.get("effect", "")
            lines.append(f"  \u2022 <b>{product}</b> ({freq}): {effect}")

    # Goal progress
    goal_progress = parsed.get("goal_progress")
    if goal_progress:
        lines.append(f"\n\U0001f4c8 <b>Прогресс:</b> {goal_progress}")

    # Signals
    signals = parsed.get("signals", [])
    if signals:
        lines.append("")
        for s in signals:
            lines.append(format_signal(s.get("level", "green"), s.get("text", "")))

    # Fixes
    fixes = parsed.get("fixes", [])
    if fixes:
        lines.append(f"\n\U0001f527 <b>Рекомендации:</b>")
        for f in fixes:
            action = f.get("action", "?")
            effect = f.get("effect", "")
            lines.append(f"  \u2022 {action}: {effect}")

    # Score
    score = parsed.get("score")
    score_comment = parsed.get("score_comment", "")
    if score is not None:
        bar_filled = int(score / 10)
        bar = "\u25fc" * bar_filled + "\u25fb" * (10 - bar_filled)
        lines.append(f"\n{bar} <b>{score}%</b>")
        if score_comment:
            lines.append(score_comment)

    # Final verdict
    verdict = parsed.get("final_verdict")
    if verdict:
        lines.append(f"\n\U0001f4ac <b>Итог:</b> {verdict}")

    text = "\n".join(lines)

    # Menu suggestion button
    menu_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"Составить меню на неделю",
            callback_data=f"weekmenu:{period_key}",
        )]
    ])

    try:
        if len(text) <= 4096:
            await callback.message.answer(text, parse_mode="HTML", reply_markup=menu_kb)
        else:
            parts = text.split("\n\n")
            chunk = ""
            for part in parts:
                if len(chunk) + len(part) + 2 > 4096:
                    await callback.message.answer(chunk, parse_mode="HTML")
                    chunk = part
                else:
                    chunk = chunk + "\n\n" + part if chunk else part
            if chunk:
                await callback.message.answer(chunk, parse_mode="HTML", reply_markup=menu_kb)
    except Exception:
        logger.exception("Failed to send report")
        await callback.message.answer("Ошибка отправки отчета.")
