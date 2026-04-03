import json
import logging

from aiogram import Bot, Router, F
from aiogram.enums import ChatAction
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bot.handlers.states import RefineState
from bot.keyboards.meal import meal_result_keyboard
from bot.models.meal import MealLog, MealItem
from bot.models.user import User
from bot.services.nutrition import parse_ai_response
from bot.services.prompts import render_prompt
from bot.services.stats import get_today_totals
from bot.services.vision.base import VisionProvider
from bot.utils.formatters import format_macros, format_progress_bar, format_signal

logger = logging.getLogger(__name__)

router = Router()


async def _load_meal(session: AsyncSession, meal_id: int, user_id: int) -> MealLog | None:
    result = await session.execute(
        select(MealLog)
        .options(selectinload(MealLog.items))
        .where(MealLog.id == meal_id, MealLog.user_id == user_id)
    )
    return result.scalar_one_or_none()


# --- save ---

@router.callback_query(F.data.startswith("save:"))
async def cb_save(
    callback: CallbackQuery, session: AsyncSession, user: User
):
    meal_id = int(callback.data.split(":")[1])
    meal = await _load_meal(session, meal_id, user.id)
    if not meal:
        await callback.answer("Запись не найдена")
        return

    meal.is_confirmed = True
    await session.commit()

    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer("Сохранено!")


# --- cancel ---

@router.callback_query(F.data.startswith("cancel:"))
async def cb_cancel(
    callback: CallbackQuery, session: AsyncSession, user: User
):
    meal_id = int(callback.data.split(":")[1])
    meal = await _load_meal(session, meal_id, user.id)
    if not meal:
        await callback.answer("Запись не найдена")
        return

    await session.delete(meal)
    await session.commit()

    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer("Отменено")


# --- refine (step 1: ask for text) ---

@router.callback_query(F.data.startswith("refine:"))
async def cb_refine(
    callback: CallbackQuery, state: FSMContext
):
    meal_id = int(callback.data.split(":")[1])
    await state.set_state(RefineState.waiting_for_text)
    await state.update_data(meal_id=meal_id)

    await callback.message.answer("Напишите, что уточнить (состав, порцию и т.д.):")
    await callback.answer()


# --- refine (step 2: process text) ---

@router.message(RefineState.waiting_for_text)
async def refine_process_text(
    message: Message,
    bot: Bot,
    session: AsyncSession,
    user: User,
    state: FSMContext,
    vision_provider: VisionProvider,
):
    data = await state.get_data()
    meal_id = data.get("meal_id")
    await state.clear()

    meal = await _load_meal(session, meal_id, user.id)
    if not meal:
        await message.answer("Запись не найдена.")
        return

    await message.answer_chat_action(ChatAction.TYPING)

    # load previous analysis
    try:
        previous_analysis = json.loads(meal.ai_description) if meal.ai_description else {}
    except json.JSONDecodeError:
        previous_analysis = {}

    prompt = render_prompt(
        "refine_meal.j2",
        previous_analysis=previous_analysis,
        user_refinement=message.text,
        response_mode=user.response_mode,
    )

    try:
        raw = await vision_provider.analyze(None, prompt)
        parsed = parse_ai_response(raw)
        total = parsed["total"]
        items_data = parsed["items"]
    except Exception:
        logger.exception("Refine failed")
        await message.answer("Не удалось пересчитать. Попробуйте еще раз.")
        return

    # update meal totals
    meal.total_calories = total.get("calories", 0)
    meal.total_protein = total.get("protein", 0)
    meal.total_fat = total.get("fat", 0)
    meal.total_carbs = total.get("carbs", 0)
    meal.ai_description = json.dumps(parsed, ensure_ascii=False)

    # replace items
    meal.items.clear()
    for item in items_data:
        meal.items.append(MealItem(
            name=item.get("name", "?"),
            calories=item.get("calories", 0),
            protein=item.get("protein", 0),
            fat=item.get("fat", 0),
            carbs=item.get("carbs", 0),
            grams=item.get("grams"),
        ))

    await session.commit()
    await session.refresh(meal)

    # format response
    lines = [f"<b>{parsed.get('description', 'Обновлено')}</b>\n"]
    for item in items_data:
        name = item.get("name", "?")
        grams = item.get("grams")
        g_str = f" (~{grams} г)" if grams else ""
        lines.append(f"{name}{g_str}")
        lines.append(
            f"  Б:{item.get('protein', 0)} Ж:{item.get('fat', 0)} "
            f"У:{item.get('carbs', 0)} | {item.get('calories', 0)} ккал"
        )

    lines.append("\n<b>--- Итого ---</b>")
    lines.append(format_macros(
        total.get("calories", 0), total.get("protein", 0),
        total.get("fat", 0), total.get("carbs", 0),
    ))

    for s in parsed.get("signals", []):
        lines.append(format_signal(s.get("level", "green"), s.get("text", "")))

    await message.answer(
        "\n".join(lines),
        reply_markup=meal_result_keyboard(meal.id),
        parse_mode="HTML",
    )


# --- today (exact match) ---

@router.callback_query(F.data == "today")
async def cb_today(
    callback: CallbackQuery, session: AsyncSession, user: User
):
    totals = await get_today_totals(session, user.id)

    lines = ["<b>Итого за сегодня:</b>\n"]
    lines.append(format_macros(
        totals["calories"], totals["protein"], totals["fat"], totals["carbs"]
    ))
    lines.append("")
    lines.append(format_progress_bar(totals["calories"], user.daily_calories_goal))

    await callback.message.answer("\n".join(lines), parse_mode="HTML")
    await callback.answer()


# --- menu ---

@router.callback_query(F.data.startswith("menu:"))
async def cb_menu(
    callback: CallbackQuery,
    session: AsyncSession,
    user: User,
    vision_provider: VisionProvider,
):
    await callback.answer("Генерирую меню...")

    user_goals = {
        "calories": user.daily_calories_goal,
        "protein": user.daily_protein_goal,
        "fat": user.daily_fat_goal,
        "carbs": user.daily_carbs_goal,
    }
    today_totals = await get_today_totals(session, user.id)

    prompt = render_prompt(
        "suggest_menu.j2", user_goals=user_goals, today_totals=today_totals
    )

    try:
        raw = await vision_provider.analyze(None, prompt)
        parsed = parse_ai_response(raw)
    except Exception:
        logger.exception("Menu suggestion failed")
        await callback.message.answer("AI-сервис недоступен.")
        return

    lines = ["<b>Предложения:</b>\n"]
    for s in parsed.get("suggestions", []):
        lines.append(f"<b>{s.get('name', '?')}</b>")
        if s.get("description"):
            lines.append(s["description"])
        lines.append(
            f"  {s.get('calories', 0)} ккал | "
            f"Б:{s.get('protein', 0)} Ж:{s.get('fat', 0)} У:{s.get('carbs', 0)}"
        )
        lines.append("")

    await callback.message.answer("\n".join(lines), parse_mode="HTML")


# --- alternatives ---

@router.callback_query(F.data.startswith("alt:"))
async def cb_alternatives(
    callback: CallbackQuery,
    session: AsyncSession,
    user: User,
    vision_provider: VisionProvider,
):
    meal_id = int(callback.data.split(":")[1])
    meal = await _load_meal(session, meal_id, user.id)
    if not meal:
        await callback.answer("Запись не найдена")
        return

    await callback.answer("Ищу альтернативы...")

    try:
        analysis = json.loads(meal.ai_description) if meal.ai_description else {}
    except json.JSONDecodeError:
        analysis = {}

    problem_signals = [
        s for s in analysis.get("signals", [])
        if s.get("level") in ("yellow", "red")
    ]

    prompt = render_prompt(
        "suggest_alternatives.j2",
        meal_analysis=analysis,
        problem_signals=problem_signals,
    )

    try:
        raw = await vision_provider.analyze(None, prompt)
        parsed = parse_ai_response(raw)
    except Exception:
        logger.exception("Alternatives suggestion failed")
        await callback.message.answer("AI-сервис недоступен.")
        return

    lines = ["<b>Чем заменить:</b>\n"]
    for alt in parsed.get("alternatives", []):
        lines.append(
            f"{alt.get('original', '?')} -> <b>{alt.get('replacement', '?')}</b>"
        )
        if alt.get("reason"):
            lines.append(f"  {alt['reason']}")
        lines.append("")

    await callback.message.answer("\n".join(lines), parse_mode="HTML")


# --- detail ---

@router.callback_query(F.data.startswith("detail:"))
async def cb_detail(
    callback: CallbackQuery, session: AsyncSession, user: User
):
    meal_id = int(callback.data.split(":")[1])
    meal = await _load_meal(session, meal_id, user.id)
    if not meal:
        await callback.answer("Запись не найдена")
        return

    total_cal = meal.total_calories or 1

    lines = ["<b>Подробный анализ:</b>\n"]
    for item in meal.items:
        pct = int(item.calories / total_cal * 100) if total_cal else 0
        lines.append(f"<b>{item.name}</b> ({item.grams or '?'} г) - {pct}%")
        lines.append(
            f"  Б:{item.protein:.0f} Ж:{item.fat:.0f} "
            f"У:{item.carbs:.0f} | {item.calories:.0f} ккал"
        )
        lines.append("")

    lines.append("<b>--- Итого ---</b>")
    lines.append(format_macros(
        meal.total_calories, meal.total_protein, meal.total_fat, meal.total_carbs
    ))

    await callback.message.answer("\n".join(lines), parse_mode="HTML")
    await callback.answer()
