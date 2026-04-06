import logging

from aiogram import Bot, Router, F
from aiogram.enums import ChatAction
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy.ext.asyncio import AsyncSession

from bot.constants import GOAL_TYPE_LABELS
from bot.models.user import User
from bot.services.prompts import render_prompt
from bot.services.stats import (
    get_period_stats,
    get_period_meals_for_prompt,
    get_today_meals,
    get_weekly_summary_for_prompt,
    format_today_meals_for_prompt,
)
from bot.services.vision.base import VisionProvider

logger = logging.getLogger(__name__)

router = Router()

MENU_PERIODS = {
    "1": ("На завтра", 1, "день"),
    "7": ("На неделю", 7, "дней"),
    "30": ("На месяц", 28, "дней"),
}


@router.message(Command("menu"))
async def cmd_menu(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="На завтра", callback_data="planmenu:1"),
            InlineKeyboardButton(text="На неделю", callback_data="planmenu:7"),
            InlineKeyboardButton(text="На месяц", callback_data="planmenu:30"),
        ]
    ])
    await message.answer(
        "\U0001f37d <b>Подбор меню</b>\n\n"
        "Составлю меню на основе твоих целей и привычного рациона.\n"
        "Выбери период:",
        reply_markup=kb,
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("planmenu:"))
async def cb_plan_menu(
    callback: CallbackQuery,
    session: AsyncSession,
    user: User,
    vision_provider: VisionProvider,
):
    period_key = callback.data.split(":")[1]
    if period_key not in MENU_PERIODS:
        await callback.answer("Неизвестный период")
        return

    label, menu_days, days_word = MENU_PERIODS[period_key]
    await callback.answer(f"Составляю меню {label.lower()}...")
    await callback.bot.send_chat_action(
        chat_id=callback.message.chat.id, action=ChatAction.TYPING
    )

    # gather context from history
    stats_data = await get_period_stats(session, user.id, days=30)
    _, frequent = await get_period_meals_for_prompt(session, user.id, days=30)

    weekly = await get_weekly_summary_for_prompt(session, user.id)

    prompt_stats = None
    if stats_data["days_tracked"] > 0:
        prompt_stats = {
            "avg_calories": int(stats_data["avg_calories"]),
            "avg_protein": int(stats_data["avg_protein"]),
            "avg_fat": int(stats_data["avg_fat"]),
            "avg_carbs": int(stats_data["avg_carbs"]),
            "patterns": weekly.get("patterns", []) if weekly else [],
        }

    # today's meals (for "tomorrow" context)
    today_meals = None
    if menu_days == 1:
        today_raw = await get_today_meals(session, user.id)
        if today_raw:
            today_meals = format_today_meals_for_prompt(today_raw)

    user_profile = {
        "goal_type": GOAL_TYPE_LABELS.get(user.goal_type, user.goal_type),
        "weight": user.weight,
        "target_weight": user.target_weight,
        "activity": user.activity_level or user.activity_description,
    }
    user_goals = {
        "calories": user.daily_calories_goal,
        "protein": user.daily_protein_goal,
        "fat": user.daily_fat_goal,
        "carbs": user.daily_carbs_goal,
    }

    prompt = render_prompt(
        "plan_menu.j2",
        menu_days=menu_days,
        menu_days_word=days_word,
        user_profile=user_profile,
        user_goals=user_goals,
        frequent_products=frequent,
        stats=prompt_stats,
        today_meals=today_meals,
    )

    try:
        response = await vision_provider.analyze(None, prompt)
    except Exception:
        logger.exception("Menu generation failed")
        await callback.message.answer("Не удалось составить меню. Попробуйте позже.")
        return

    if not response or not response.strip():
        await callback.message.answer("AI вернул пустой ответ.")
        return

    # send response, split if needed
    try:
        if len(response) <= 4096:
            await callback.message.answer(response, parse_mode=None)
        else:
            # split by double newline to keep formatting
            parts = response.split("\n\n")
            chunk = ""
            for part in parts:
                if len(chunk) + len(part) + 2 > 4096:
                    if chunk:
                        await callback.message.answer(chunk, parse_mode=None)
                    chunk = part
                else:
                    chunk = chunk + "\n\n" + part if chunk else part
            if chunk:
                await callback.message.answer(chunk, parse_mode=None)
    except Exception:
        logger.exception("Failed to send menu")
        await callback.message.answer("Ошибка отправки меню.")
