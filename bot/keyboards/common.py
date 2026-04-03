from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Да", callback_data="confirm:yes"),
            InlineKeyboardButton(text="Нет", callback_data="confirm:no"),
        ],
    ])
