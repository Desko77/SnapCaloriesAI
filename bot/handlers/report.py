import json
import logging

from aiogram import Router, F
from aiogram.enums import ChatAction
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.user import User
from bot.services.nutrition import parse_ai_response
from bot.services.prompts import render_prompt
from bot.services.stats import get_period_stats, get_period_meals_for_prompt
from bot.services.vision.base import VisionProvider
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
    await callback.message.answer_chat_action(ChatAction.TYPING)

    stats = await get_period_stats(session, user.id, days=days)
    if stats["days_tracked"] == 0:
        await callback.message.answer("Нет данных за этот период.")
        return

    meals, frequent = await get_period_meals_for_prompt(session, user.id, days=days)

    # user profile for goal context
    user_profile = {
        "goal_type": {
            "loss": "Похудение",
            "gain": "Набор массы",
            "maintain": "Поддержание веса",
        }.get(user.goal_type, user.goal_type),
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

    # format stats for prompt
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
        meals=meals,
        frequent_products=frequent,
    )

    try:
        raw = await vision_provider.analyze(None, prompt)
        parsed = parse_ai_response(raw)
    except Exception:
        logger.exception("Report generation failed")
        await callback.message.answer("Не удалось сгенерировать отчет. Попробуйте позже.")
        return

    # format response
    lines = [f"<b>Отчет за {period_label.lower()}</b>\n"]

    summary = parsed.get("summary")
    if summary:
        lines.append(summary)

    trend = parsed.get("trend")
    if trend:
        lines.append(f"\n<b>Тренд:</b> {trend}")

    patterns = parsed.get("patterns", [])
    if patterns:
        lines.append("\n<b>Паттерны:</b>")
        for p in patterns:
            lines.append(f"- {p}")

    goal_progress = parsed.get("goal_progress")
    if goal_progress:
        lines.append(f"\n<b>Прогресс к цели:</b> {goal_progress}")

    signals = parsed.get("signals", [])
    if signals:
        lines.append("")
        for s in signals:
            lines.append(format_signal(s.get("level", "green"), s.get("text", "")))

    recommendations = parsed.get("recommendations", [])
    if recommendations:
        lines.append("\n<b>Рекомендации:</b>")
        for r in recommendations:
            lines.append(f"- {r}")

    key_points = parsed.get("key_points", [])
    if key_points:
        lines.append("\n<b>Главное:</b>")
        for kp in key_points:
            lines.append(f"- {kp}")

    await callback.message.answer("\n".join(lines), parse_mode="HTML")
