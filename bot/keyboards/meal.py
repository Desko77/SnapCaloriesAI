from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def meal_result_keyboard(meal_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Сохранить", callback_data=f"save:{meal_id}"),
            InlineKeyboardButton(text="Уточнить", callback_data=f"refine:{meal_id}"),
            InlineKeyboardButton(text="Отмена", callback_data=f"cancel:{meal_id}"),
        ],
        [
            InlineKeyboardButton(text="Итог за день", callback_data="today"),
            InlineKeyboardButton(text="Предложи меню", callback_data=f"menu:{meal_id}"),
        ],
        [
            InlineKeyboardButton(text="Чем заменить?", callback_data=f"alt:{meal_id}"),
            InlineKeyboardButton(text="Подробный анализ", callback_data=f"detail:{meal_id}"),
        ],
    ])
