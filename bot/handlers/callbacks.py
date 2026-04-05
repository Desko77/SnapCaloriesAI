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
from bot.services.stats import (
    get_today_meals,
    get_today_totals,
    get_weekly_summary_for_prompt,
    format_today_meals_for_prompt,
)
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

    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
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

    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
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

    await bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)

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
    except Exception:
        logger.exception("Refine: AI call failed")
        await message.answer("AI-сервис недоступен. Попробуйте позже.")
        return

    try:
        total = parsed["total"]
        items_data = parsed["items"]
    except KeyError:
        logger.error("Refine: AI response missing keys: %s", parsed)
        await message.answer("AI вернул неполный ответ. Попробуйте еще раз.")
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


# --- daily AI analysis ---

@router.callback_query(F.data == "daily_ai")
async def cb_daily_ai(
    callback: CallbackQuery,
    session: AsyncSession,
    user: User,
    vision_provider: VisionProvider,
):
    meals_raw = await get_today_meals(session, user.id)
    if not meals_raw:
        await callback.answer("Нет приемов пищи за сегодня")
        return

    await callback.answer("Генерирую AI-анализ дня...")
    await callback.bot.send_chat_action(chat_id=callback.message.chat.id, action=ChatAction.TYPING)

    from bot.constants import GOAL_TYPE_LABELS

    totals = await get_today_totals(session, user.id)
    meals = format_today_meals_for_prompt(meals_raw)

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

    prompt = render_prompt(
        "daily_summary.j2",
        user_profile=user_profile,
        user_goals=user_goals,
        meals=meals,
        day_totals=totals,
    )

    try:
        raw = await vision_provider.analyze(None, prompt)
        parsed = parse_ai_response(raw)
    except Exception:
        logger.exception("Daily AI analysis failed")
        await callback.message.answer("Не удалось сгенерировать анализ. Попробуйте позже.")
        return

    # format response
    lines = ["\U0001f4ca <b>AI-анализ дня</b>\n"]

    # meals summary
    meals_summary = parsed.get("meals_summary", [])
    if meals_summary:
        for ms in meals_summary:
            lines.append(
                f"\U0001f37d <b>{ms.get('name', '?')}</b>: {ms.get('items', '')}"
            )
            lines.append(f"   ~{ms.get('calories', 0)} ккал / {ms.get('protein', 0)}г белка")
        lines.append("")

    # totals vs goal
    t = parsed.get("totals", {})
    if t:
        cal = t.get("calories", 0)
        cal_goal = t.get("calories_goal", user.daily_calories_goal)
        cal_diff = t.get("calories_diff", cal - cal_goal)
        diff_sign = "+" if cal_diff > 0 else ""
        lines.append(f"\U0001f525 <b>Итого: {cal} ккал</b> (цель {cal_goal}, {diff_sign}{cal_diff})")
        lines.append(
            f"\U0001f4aa Б:{t.get('protein', 0)}г  "
            f"\U0001f9c8 Ж:{t.get('fat', 0)}г  "
            f"\U0001f33e У:{t.get('carbs', 0)}г"
        )

    # pluses
    plus = parsed.get("analysis_plus", [])
    if plus:
        lines.append(f"\n\u2705 <b>Плюсы:</b>")
        for p in plus:
            lines.append(f"  \u2022 {p}")

    # minuses
    minus = parsed.get("analysis_minus", [])
    if minus:
        lines.append(f"\n\u274c <b>Проблемы:</b>")
        for m in minus:
            lines.append(f"  \u2022 {m}")

    # hidden enemies
    enemies = parsed.get("hidden_enemies", [])
    if enemies:
        lines.append(f"\n\u26a0\ufe0f <b>Скрытые враги:</b>")
        for e in enemies:
            product = e.get("product", "?")
            problem = e.get("problem", "")
            lines.append(f"  \u2022 <b>{product}</b> - {problem}")

    # fixes
    fixes = parsed.get("fixes", [])
    if fixes:
        lines.append(f"\n\U0001f527 <b>Как сделать идеально:</b>")
        for f in fixes:
            lines.append(f"  \u2022 {f.get('replace', '?')} \u2192 {f.get('with', '?')}: {f.get('effect', '')}")

    # after fixes
    after = parsed.get("after_fixes", {})
    if after:
        lines.append(f"\n\U0001f4a1 <b>Идеальный вариант этого дня:</b> ~{after.get('calories', '?')} ккал, "
                      f"Б:{after.get('protein', '?')}г - {after.get('verdict', '')}")

    # score
    score = parsed.get("score")
    score_comment = parsed.get("score_comment", "")
    if score is not None:
        bar_filled = int(score / 10)
        bar = "\u25fc" * bar_filled + "\u25fb" * (10 - bar_filled)
        lines.append(f"\n{bar} <b>{score}%</b>")
        if score_comment:
            lines.append(score_comment)

    # final verdict
    verdict = parsed.get("final_verdict")
    if verdict:
        lines.append(f"\n\U0001f4ac <b>Итог:</b> {verdict}")

    text = "\n".join(lines)

    try:
        if len(text) <= 4096:
            await callback.message.answer(text, parse_mode="HTML")
        else:
            # split by double newline to avoid breaking formatting
            parts = text.split("\n\n")
            chunk = ""
            for part in parts:
                if len(chunk) + len(part) + 2 > 4096:
                    await callback.message.answer(chunk, parse_mode="HTML")
                    chunk = part
                else:
                    chunk = chunk + "\n\n" + part if chunk else part
            if chunk:
                await callback.message.answer(chunk, parse_mode="HTML")
    except Exception:
        logger.exception("Failed to send daily AI analysis")
        await callback.message.answer("Ошибка отправки. Попробуйте еще раз.")


# --- weekly menu from report ---

@router.callback_query(F.data.startswith("weekmenu:"))
async def cb_weekmenu(
    callback: CallbackQuery,
    session: AsyncSession,
    user: User,
    vision_provider: VisionProvider,
):
    from bot.services.stats import get_period_stats, get_period_meals_for_prompt
    from bot.constants import GOAL_TYPE_LABELS

    period_key = callback.data.split(":")[1]
    periods = {"7": 7, "30": 30, "all": 365}
    days = periods.get(period_key, 7)

    await callback.answer("Составляю меню на неделю...")
    await callback.bot.send_chat_action(chat_id=callback.message.chat.id, action=ChatAction.TYPING)

    stats = await get_period_stats(session, user.id, days=days)
    _, frequent = await get_period_meals_for_prompt(session, user.id, days=days)

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
    prompt_stats = {
        "avg_calories": int(stats["avg_calories"]),
        "avg_protein": int(stats["avg_protein"]),
        "avg_fat": int(stats["avg_fat"]),
        "avg_carbs": int(stats["avg_carbs"]),
    } if stats["days_tracked"] > 0 else None

    prompt = render_prompt(
        "weekly_menu.j2",
        user_profile=user_profile,
        user_goals=user_goals,
        frequent_products=frequent,
        stats=prompt_stats,
    )

    try:
        response = await vision_provider.analyze(None, prompt)
    except Exception:
        logger.exception("Weekly menu generation failed")
        await callback.message.answer("Не удалось составить меню. Попробуйте позже.")
        return

    if not response or not response.strip():
        await callback.message.answer("AI вернул пустой ответ.")
        return

    try:
        if len(response) <= 4096:
            await callback.message.answer(response, parse_mode=None)
        else:
            for i in range(0, len(response), 4096):
                chunk = response[i:i + 4096]
                await callback.message.answer(chunk, parse_mode=None)
    except Exception:
        logger.exception("Failed to send weekly menu")
        await callback.message.answer("Ошибка отправки меню.")


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

    total_cal = meal.total_calories

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


# --- AI suggestion ---

@router.callback_query(F.data.startswith("sug:"))
async def cb_suggestion(
    callback: CallbackQuery,
    session: AsyncSession,
    user: User,
    vision_provider: VisionProvider,
):
    parts = callback.data.split(":")
    meal_id = int(parts[1])
    sug_idx = int(parts[2])

    meal = await _load_meal(session, meal_id, user.id)
    if not meal:
        await callback.answer("Запись не найдена")
        return

    # extract suggestion prompt from stored analysis
    try:
        analysis = json.loads(meal.ai_description) if meal.ai_description else {}
        suggestions = analysis.get("suggestions", [])
        suggestion = suggestions[sug_idx]
    except (json.JSONDecodeError, IndexError, KeyError):
        await callback.answer("Предложение недоступно")
        return

    await callback.answer("Генерирую...")
    await callback.bot.send_chat_action(chat_id=callback.message.chat.id, action=ChatAction.TYPING)

    user_goals = {
        "calories": user.daily_calories_goal,
        "protein": user.daily_protein_goal,
        "fat": user.daily_fat_goal,
        "carbs": user.daily_carbs_goal,
    }
    user_profile = {
        "goal_type": user.goal_type,
        "weight": user.weight,
        "target_weight": user.target_weight,
        "height": user.height,
    }
    today_totals = await get_today_totals(session, user.id)
    today_meals_raw = await get_today_meals(session, user.id)
    today_meals = format_today_meals_for_prompt(today_meals_raw)
    weekly_summary = await get_weekly_summary_for_prompt(session, user.id)

    prompt = render_prompt(
        "execute_suggestion.j2",
        suggestion_prompt=suggestion.get("prompt", suggestion.get("text", "")),
        user_profile=user_profile,
        user_goals=user_goals,
        today_totals=today_totals,
        today_meals=today_meals,
        weekly_summary=weekly_summary,
    )

    try:
        response = await vision_provider.analyze(None, prompt)
    except Exception:
        logger.exception("Suggestion execution failed")
        await callback.message.answer("AI-сервис недоступен.")
        return

    if not response or not response.strip():
        await callback.message.answer("AI вернул пустой ответ. Попробуйте еще раз.")
        return

    # Telegram message limit: 4096 chars
    try:
        if len(response) <= 4096:
            await callback.message.answer(response, parse_mode=None)
        else:
            # split long responses into chunks
            for i in range(0, len(response), 4096):
                chunk = response[i:i + 4096]
                await callback.message.answer(chunk, parse_mode=None)
    except Exception:
        logger.exception("Failed to send suggestion response")
        await callback.message.answer("Ошибка отправки ответа. Попробуйте еще раз.")
