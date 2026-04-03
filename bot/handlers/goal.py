from datetime import date, datetime

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.handlers.states import GoalEditState
from bot.models.user import User

router = Router()

GOAL_TYPE_LABELS = {
    "loss": "Похудение",
    "maintain": "Поддержание веса",
    "muscle": "Набор мышечной массы",
    "gain": "Набор веса",
    "recomp": "Рекомпозиция (жир->мышцы)",
    "health": "Здоровое питание",
    "energy": "Больше энергии",
}

KBJU_FIELDS = {
    "calories": ("daily_calories_goal", "Калории (ккал)"),
    "protein": ("daily_protein_goal", "Белки (г)"),
    "fat": ("daily_fat_goal", "Жиры (г)"),
    "carbs": ("daily_carbs_goal", "Углеводы (г)"),
}

BODY_FIELDS = {
    "weight": ("weight", "Текущий вес (кг)"),
    "height": ("height", "Рост (см)"),
    "target_weight": ("target_weight", "Целевой вес (кг)"),
    "deadline": ("goal_deadline", "Срок (ДД.ММ.ГГГГ)"),
}

ALL_FIELDS = {**KBJU_FIELDS, **BODY_FIELDS}


def _goal_text(user: User) -> str:
    goal_label = GOAL_TYPE_LABELS.get(user.goal_type, "Не задана")
    lines = [f"<b>Цель:</b> {goal_label}"]

    if user.weight:
        w = f"Текущий вес: {user.weight:.1f} кг"
        if user.target_weight:
            w += f" | Целевой: {user.target_weight:.1f} кг"
        lines.append(w)
    if user.height:
        lines.append(f"Рост: {user.height:.0f} см")
    if user.goal_deadline:
        lines.append(f"Срок: до {user.goal_deadline.strftime('%d.%m.%Y')}")

    lines.append("")
    lines.append("<b>Дневные нормы КБЖУ:</b>")
    lines.append(
        f"Калории: {user.daily_calories_goal} | "
        f"Белки: {user.daily_protein_goal} | "
        f"Жиры: {user.daily_fat_goal} | "
        f"Углеводы: {user.daily_carbs_goal}"
    )
    return "\n".join(lines)


def _goal_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Тип цели", callback_data="goal:goal_type"),
            InlineKeyboardButton(text="Вес", callback_data="goal:weight"),
        ],
        [
            InlineKeyboardButton(text="Целевой вес", callback_data="goal:target_weight"),
            InlineKeyboardButton(text="Рост", callback_data="goal:height"),
        ],
        [
            InlineKeyboardButton(text="Срок", callback_data="goal:deadline"),
        ],
        [
            InlineKeyboardButton(text="Калории", callback_data="goal:calories"),
            InlineKeyboardButton(text="Белки", callback_data="goal:protein"),
        ],
        [
            InlineKeyboardButton(text="Жиры", callback_data="goal:fat"),
            InlineKeyboardButton(text="Углеводы", callback_data="goal:carbs"),
        ],
    ])


@router.message(Command("goal"))
async def cmd_goal(message: Message, user: User):
    await message.answer(
        _goal_text(user) + "\n\nНажмите, чтобы изменить:",
        reply_markup=_goal_keyboard(),
        parse_mode="HTML",
    )


# --- goal type selection ---

@router.callback_query(F.data == "goal:goal_type")
async def cb_goal_type(callback: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=label, callback_data=f"setgoal:{key}")]
        for key, label in GOAL_TYPE_LABELS.items()
    ])
    await callback.message.answer("Выберите цель:", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("setgoal:"))
async def cb_set_goal_type(
    callback: CallbackQuery, session: AsyncSession, user: User
):
    goal_type = callback.data.split(":")[1]
    if goal_type not in GOAL_TYPE_LABELS:
        await callback.answer("Неизвестный тип")
        return

    user.goal_type = goal_type
    await session.commit()

    label = GOAL_TYPE_LABELS[goal_type]
    await callback.message.answer(
        f"Цель: <b>{label}</b>",
        reply_markup=_goal_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer(f"Установлено: {label}")


# --- numeric/date fields ---

@router.callback_query(F.data.startswith("goal:"))
async def cb_goal_edit(callback: CallbackQuery, state: FSMContext):
    param = callback.data.split(":")[1]
    if param == "goal_type":
        return  # handled above
    if param not in ALL_FIELDS:
        await callback.answer("Неизвестный параметр")
        return

    _, label = ALL_FIELDS[param]
    await state.set_state(GoalEditState.waiting_for_value)
    await state.update_data(param=param)

    hint = ""
    if param == "deadline":
        hint = " (формат: ДД.ММ.ГГГГ)"

    await callback.message.answer(
        f"Введите <b>{label}</b>{hint}:", parse_mode="HTML"
    )
    await callback.answer()


@router.message(GoalEditState.waiting_for_value)
async def goal_process_value(
    message: Message, session: AsyncSession, user: User, state: FSMContext
):
    data = await state.get_data()
    param = data.get("param")
    await state.clear()

    if param not in ALL_FIELDS:
        await message.answer("Ошибка, попробуйте /goal заново.")
        return

    attr, label = ALL_FIELDS[param]
    text = message.text.strip()

    # parse deadline as date
    if param == "deadline":
        try:
            parsed_date = datetime.strptime(text, "%d.%m.%Y").date()
            if parsed_date <= date.today():
                await message.answer("Дата должна быть в будущем. Попробуйте /goal.")
                return
            setattr(user, attr, parsed_date)
        except ValueError:
            await message.answer("Формат: ДД.ММ.ГГГГ. Попробуйте /goal.")
            return
    else:
        # numeric fields
        try:
            value = float(text)
            if value <= 0:
                raise ValueError
            # integer fields for KBJU
            if param in KBJU_FIELDS:
                value = int(value)
            setattr(user, attr, value)
        except (ValueError, TypeError):
            await message.answer("Введите положительное число. Попробуйте /goal.")
            return

    await session.commit()

    await message.answer(
        _goal_text(user),
        reply_markup=_goal_keyboard(),
        parse_mode="HTML",
    )


# --- settings ---

@router.message(Command("settings"))
async def cmd_settings(message: Message, user: User):
    mode_text = "Компактный" if user.response_mode == "compact" else "Развернутый"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"Режим: {mode_text}",
            callback_data="setting:response_mode",
        )]
    ])
    await message.answer("<b>Настройки:</b>", reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data == "setting:response_mode")
async def cb_toggle_response_mode(
    callback: CallbackQuery, session: AsyncSession, user: User
):
    user.response_mode = "detailed" if user.response_mode == "compact" else "compact"
    await session.commit()

    mode_text = "Компактный" if user.response_mode == "compact" else "Развернутый"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"Режим: {mode_text}",
            callback_data="setting:response_mode",
        )]
    ])
    await callback.message.edit_reply_markup(reply_markup=kb)
    await callback.answer(f"Режим: {mode_text}")
