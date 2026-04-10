from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def meal_result_keyboard(
    meal_id: int, suggestions: list[dict] | None = None
) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text="\u2705 Сохранить",
                callback_data=f"confirm:{meal_id}",
            ),
            InlineKeyboardButton(
                text="Уточнить",
                callback_data=f"refine:{meal_id}",
            ),
        ],
        [
            InlineKeyboardButton(text="Итог за день", callback_data="today"),
            InlineKeyboardButton(text="Подробнее", callback_data=f"detail:{meal_id}"),
        ],
        [
            InlineKeyboardButton(
                text="Не сохранять",
                callback_data=f"cancel:{meal_id}",
            ),
        ],
    ]

    # dynamic AI suggestions
    if suggestions:
        for i, s in enumerate(suggestions[:3]):
            text = s.get("text", "")[:32]
            rows.append([
                InlineKeyboardButton(text=text, callback_data=f"sug:{meal_id}:{i}")
            ])

    return InlineKeyboardMarkup(inline_keyboard=rows)
