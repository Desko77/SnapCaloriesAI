import logging

from aiogram import Bot, Router, F
from aiogram.enums import ChatAction
from aiogram.filters import StateFilter
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.constants import GOAL_TYPE_LABELS
from bot.models.user import User
from bot.services.prompts import render_prompt
from bot.services.stats import get_today_totals
from bot.services.vision.base import VisionProvider

logger = logging.getLogger(__name__)

router = Router()

NOT_FOOD_REPLY = (
    "\U0001f37d <b>Я - AI-нутрициолог SnapCalories.</b>\n\n"
    "Могу помочь с:\n"
    "\u2022 Анализ еды по фото\n"
    "\u2022 Подсчет калорий и БЖУ\n"
    "\u2022 Составление меню\n"
    "\u2022 Советы по диете и похудению\n"
    "\u2022 Замены продуктов\n\n"
    "Отправь фото еды или задай вопрос про питание."
)


@router.message(F.text, StateFilter(None))
async def handle_text(
    message: Message,
    bot: Bot,
    session: AsyncSession,
    user: User,
    vision_provider: VisionProvider,
):
    text = message.text.strip()
    if not text:
        return

    # Skip commands (should be handled by other routers)
    if text.startswith("/"):
        return

    await bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)

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
    today_totals = await get_today_totals(session, user.id)

    prompt = render_prompt(
        "free_question.j2",
        user_question=text,
        user_profile=user_profile,
        user_goals=user_goals,
        today_totals=today_totals,
    )

    try:
        response = await vision_provider.analyze(None, prompt)
    except Exception:
        logger.exception("Free question AI call failed")
        await message.answer("AI-сервис недоступен. Попробуйте позже.")
        return

    if not response or not response.strip():
        await message.answer("AI вернул пустой ответ. Попробуйте переформулировать.")
        return

    # Check if AI returned the not-food marker
    if "NOT_FOOD_TOPIC" in response.strip():
        await message.answer(NOT_FOOD_REPLY, parse_mode="HTML")
        return

    # Send AI response (plain text, may be long)
    try:
        if len(response) <= 4096:
            await message.answer(response, parse_mode=None)
        else:
            for i in range(0, len(response), 4096):
                await message.answer(response[i:i + 4096], parse_mode=None)
    except Exception:
        logger.exception("Failed to send free question response")
        await message.answer("Ошибка отправки ответа.")
