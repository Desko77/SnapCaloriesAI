from datetime import date, datetime

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.constants import GOAL_TYPE_LABELS
from bot.handlers.states import GoalEditState
from bot.models.user import User

router = Router()

KBJU_FIELDS = {
    "calories": ("daily_calories_goal", "Калории (ккал)"),
    "protein": ("daily_protein_goal", "Белки (г)"),
    "fat": ("daily_fat_goal", "Жиры (г)"),
    "carbs": ("daily_carbs_goal", "Углеводы (г)"),
}

BODY_FIELDS = {
    "age": ("age", "Возраст"),
    "weight": ("weight", "Текущий вес (кг)"),
    "height": ("height", "Рост (см)"),
    "target_weight": ("target_weight", "Целевой вес (кг)"),
    "deadline": ("goal_deadline", "Срок (ДД.ММ.ГГГГ)"),
    "activity_desc": ("activity_description", "Образ жизни (своими словами)"),
}

ALL_FIELDS = {**KBJU_FIELDS, **BODY_FIELDS}

ACTIVITY_LABELS = {
    "sedentary": "Сидячий (офис, мало движения)",
    "light": "Легкий (прогулки, легкая активность)",
    "moderate": "Умеренный (тренировки 2-3 раза/нед)",
    "active": "Активный (тренировки 4-5 раз/нед)",
    "athlete": "Спортсмен (ежедневные тренировки)",
}

GENDER_LABELS = {
    "male": "Мужской",
    "female": "Женский",
}


def _goal_text(user: User) -> str:
    goal_label = GOAL_TYPE_LABELS.get(user.goal_type, "Не задана")
    lines = [f"\U0001f3af <b>Цель:</b> {goal_label}"]

    # profile
    profile_parts = []
    if user.gender:
        profile_parts.append(GENDER_LABELS.get(user.gender, user.gender))
    if user.age:
        profile_parts.append(f"{user.age} лет")
    if profile_parts:
        lines.append(f"\U0001f464 {', '.join(profile_parts)}")

    if user.weight:
        w = f"\u2696\ufe0f Вес: {user.weight:.1f} кг"
        if user.target_weight:
            w += f" \u2192 {user.target_weight:.1f} кг"
        lines.append(w)
    if user.height:
        lines.append(f"\U0001f4cf Рост: {user.height:.0f} см")
    if user.activity_level:
        lines.append(f"\U0001f3c3 {ACTIVITY_LABELS.get(user.activity_level, user.activity_level)}")
    elif user.activity_description:
        lines.append(f"\U0001f3c3 {user.activity_description}")
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
            InlineKeyboardButton(text="\U0001f464 Пол", callback_data="goal:gender"),
            InlineKeyboardButton(text="\U0001f382 Возраст", callback_data="goal:age"),
        ],
        [
            InlineKeyboardButton(text="\u2696\ufe0f Вес", callback_data="goal:weight"),
            InlineKeyboardButton(text="\U0001f4cf Рост", callback_data="goal:height"),
        ],
        [
            InlineKeyboardButton(text="\U0001f3c3 Активность", callback_data="goal:activity"),
            InlineKeyboardButton(text="\U0001f3af Тип цели", callback_data="goal:goal_type"),
        ],
        [
            InlineKeyboardButton(text="Целевой вес", callback_data="goal:target_weight"),
            InlineKeyboardButton(text="Срок", callback_data="goal:deadline"),
        ],
        [
            InlineKeyboardButton(text="Образ жизни (текст)", callback_data="goal:activity_desc"),
        ],
        [
            InlineKeyboardButton(text="\U0001f525 Калории", callback_data="goal:calories"),
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


# --- gender selection ---

@router.callback_query(F.data == "goal:gender")
async def cb_gender(callback: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=label, callback_data=f"setgender:{key}")]
        for key, label in GENDER_LABELS.items()
    ])
    await callback.message.answer("Выберите пол:", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("setgender:"))
async def cb_set_gender(callback: CallbackQuery, session: AsyncSession, user: User):
    gender = callback.data.split(":")[1]
    if gender not in GENDER_LABELS:
        await callback.answer("Неизвестный вариант")
        return
    user.gender = gender
    await session.commit()
    await callback.message.answer(
        _goal_text(user), reply_markup=_goal_keyboard(), parse_mode="HTML",
    )
    await callback.answer(f"Пол: {GENDER_LABELS[gender]}")


# --- activity level selection ---

@router.callback_query(F.data == "goal:activity")
async def cb_activity(callback: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=label, callback_data=f"setactivity:{key}")]
        for key, label in ACTIVITY_LABELS.items()
    ])
    await callback.message.answer("Выберите уровень активности:", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("setactivity:"))
async def cb_set_activity(callback: CallbackQuery, session: AsyncSession, user: User):
    level = callback.data.split(":")[1]
    if level not in ACTIVITY_LABELS:
        await callback.answer("Неизвестный вариант")
        return
    user.activity_level = level
    await session.commit()
    await callback.message.answer(
        _goal_text(user), reply_markup=_goal_keyboard(), parse_mode="HTML",
    )
    await callback.answer(f"Активность: {ACTIVITY_LABELS[level]}")


# --- numeric/date/text fields ---

@router.callback_query(F.data.startswith("goal:"))
async def cb_goal_edit(callback: CallbackQuery, state: FSMContext):
    param = callback.data.split(":")[1]
    if param in ("goal_type", "gender", "activity"):
        return  # handled by specific handlers above
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

    # text fields (free-form)
    if param == "activity_desc":
        setattr(user, attr, text[:500])
    # parse deadline as date
    elif param == "deadline":
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
            # integer fields for KBJU and age
            if param in KBJU_FIELDS or param == "age":
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
