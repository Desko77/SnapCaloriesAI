import logging

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.user import User
from bot.services.vision.base import VisionProvider
from bot.handlers.history import _send_period_report

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

    await _send_period_report(
        callback.message, callback.bot, session, user, vision_provider,
        days=days, period_label=period_label,
    )
