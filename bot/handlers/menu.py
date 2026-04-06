import calendar
import json
import logging
from datetime import date, timedelta

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
from bot.services.meal_plan import save_meal_plan
from bot.services.nutrition import parse_ai_response
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

WEEKDAYS_RU = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


def _compute_dates(period_key: str) -> tuple[date, date, int, str]:
    """Compute start_date, end_date, menu_days, period_type for a given period key."""
    tomorrow = date.today() + timedelta(days=1)

    if period_key == "1":
        return tomorrow, tomorrow, 1, "day"

    if period_key == "7":
        end = tomorrow + timedelta(days=6)
        return tomorrow, end, 7, "week"

    # month: from tomorrow to end of current month
    _, last_day = calendar.monthrange(tomorrow.year, tomorrow.month)
    end = date(tomorrow.year, tomorrow.month, last_day)
    days = (end - tomorrow).days + 1
    return tomorrow, end, days, "month"


def _format_plan_for_telegram(parsed: dict) -> str:
    """Convert parsed JSON plan to readable Telegram HTML text."""
    lines = []

    for day_data in parsed.get("days", []):
        label = day_data.get("day_label", "?")
        lines.append(f"\U0001f4c5 <b>{label}</b>")

        for meal in day_data.get("meals", []):
            name = meal.get("name", "?")
            items = meal.get("items", "")
            cal = meal.get("calories", 0)
            pro = meal.get("protein", 0)
            fat = meal.get("fat", 0)
            carbs = meal.get("carbs", 0)
            lines.append(f"  \u25aa <b>{name}</b>: {items}")
            lines.append(
                f"    {cal} ккал | \U0001f4aa {pro} | \U0001f9c8 {fat} | \U0001f33e {carbs}"
            )

        total = day_data.get("total", {})
        if total:
            lines.append(
                f"  <b>Итого:</b> {total.get('calories', 0)} ккал | "
                f"\U0001f4aa {total.get('protein', 0)} | "
                f"\U0001f9c8 {total.get('fat', 0)} | "
                f"\U0001f33e {total.get('carbs', 0)}"
            )
        lines.append("")

    shopping = parsed.get("shopping_list", [])
    if shopping:
        lines.append("\U0001f6d2 <b>Список закупок:</b>")
        lines.append(", ".join(shopping))

    return "\n".join(lines)


async def _send_long_message(message: Message, text: str, parse_mode: str | None = "HTML"):
    """Send a message, splitting by double newline if over 4096 chars."""
    if len(text) <= 4096:
        await message.answer(text, parse_mode=parse_mode)
        return

    parts = text.split("\n\n")
    chunk = ""
    for part in parts:
        if len(chunk) + len(part) + 2 > 4096:
            if chunk:
                await message.answer(chunk, parse_mode=parse_mode)
            chunk = part
        else:
            chunk = chunk + "\n\n" + part if chunk else part
    if chunk:
        await message.answer(chunk, parse_mode=parse_mode)


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
    if period_key not in ("1", "7", "30"):
        await callback.answer("Неизвестный период")
        return

    start_dt, end_dt, menu_days, period_type = _compute_dates(period_key)

    labels = {"1": "На завтра", "7": "На неделю", "30": "На месяц"}
    await callback.answer(f"Составляю меню {labels[period_key].lower()}...")
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

    days_word = "день" if menu_days == 1 else "дней"

    prompt = render_prompt(
        "plan_menu.j2",
        menu_days=menu_days,
        menu_days_word=days_word,
        start_date=start_dt.strftime("%d.%m"),
        end_date=end_dt.strftime("%d.%m"),
        user_profile=user_profile,
        user_goals=user_goals,
        frequent_products=frequent,
        stats=prompt_stats,
        today_meals=today_meals,
    )

    try:
        raw_response = await vision_provider.analyze(None, prompt)
    except Exception:
        logger.exception("Menu generation failed")
        await callback.message.answer("Не удалось составить меню. Попробуйте позже.")
        return

    if not raw_response or not raw_response.strip():
        await callback.message.answer("AI вернул пустой ответ.")
        return

    # try to parse JSON and save
    saved = False
    try:
        parsed = parse_ai_response(raw_response)
        if "days" in parsed:
            await save_meal_plan(
                session, user.id, period_type, start_dt, end_dt, parsed, raw_response,
            )
            saved = True

            # format nice HTML
            text = _format_plan_for_telegram(parsed)
            if saved:
                text += f"\n\n\u2705 <b>План сохранен ({start_dt.strftime('%d.%m')} - {end_dt.strftime('%d.%m')}).</b>"
                text += "\nБуду сравнивать с фактическим питанием."
            await _send_long_message(callback.message, text)
            return
    except (json.JSONDecodeError, KeyError):
        logger.warning("Could not parse menu as JSON, sending raw text")

    # fallback: send raw text if JSON parsing failed
    await _send_long_message(callback.message, raw_response, parse_mode=None)
