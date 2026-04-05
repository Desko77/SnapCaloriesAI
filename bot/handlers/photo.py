import json
import logging
from datetime import datetime
from pathlib import Path

from aiogram import Bot, Router, F
from aiogram.enums import ChatAction
from aiogram.filters import StateFilter
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

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
from bot.utils.formatters import format_macros_range, format_signal

logger = logging.getLogger(__name__)

from bot.constants import GOAL_TYPE_LABELS

router = Router()


def _avg(lo, hi):
    return (lo + hi) / 2


def _range_str(lo, hi):
    if lo == hi:
        return str(int(lo))
    return f"{int(lo)}-{int(hi)}"


@router.message(F.photo, StateFilter(None))
async def handle_photo(
    message: Message,
    bot: Bot,
    session: AsyncSession,
    user: User,
    vision_provider: VisionProvider,
):
    await bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)

    # download photo
    photo = message.photo[-1]
    file = await bot.get_file(photo.file_id)
    bio = await bot.download_file(file.file_path)
    image_data = bio.read()

    # save photo to disk for future app usage
    photos_dir = Path("data/photos") / str(user.telegram_id)
    photos_dir.mkdir(parents=True, exist_ok=True)
    photo_filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
    photo_path = photos_dir / photo_filename

    # build context
    user_goals = {
        "calories": user.daily_calories_goal,
        "protein": user.daily_protein_goal,
        "fat": user.daily_fat_goal,
        "carbs": user.daily_carbs_goal,
    }
    today_totals = await get_today_totals(session, user.id)
    today_meals_raw = await get_today_meals(session, user.id)
    today_meals = format_today_meals_for_prompt(today_meals_raw)
    weekly_summary = await get_weekly_summary_for_prompt(session, user.id)

    user_profile = {
        "goal_type": GOAL_TYPE_LABELS.get(user.goal_type, user.goal_type),
        "gender": user.gender,
        "age": user.age,
        "weight": user.weight,
        "height": user.height,
        "target_weight": user.target_weight,
        "activity": user.activity_level or user.activity_description,
    }

    prompt = render_prompt(
        "analyze_photo.j2",
        user_comment=message.caption,
        user_profile=user_profile,
        user_goals=user_goals,
        today_totals=today_totals,
        today_meals=today_meals,
        weekly_summary=weekly_summary,
        response_mode=user.response_mode,
    )

    # call AI
    try:
        raw_response = await vision_provider.analyze(image_data, prompt)
        parsed = parse_ai_response(raw_response)
    except json.JSONDecodeError:
        logger.exception("Failed to parse AI response")
        await message.answer("AI вернул неожиданный формат. Попробуйте еще раз.")
        return
    except Exception:
        logger.exception("Vision provider error")
        await message.answer("AI-сервис недоступен. Попробуйте позже.")
        return

    # validate required keys
    try:
        items_data = parsed["items"]
        total = parsed["total"]
    except KeyError:
        logger.error("AI response missing required keys: %s", parsed)
        await message.answer("AI вернул неполный ответ. Попробуйте еще раз.")
        return

    # save photo only after successful AI analysis
    photo_path.write_bytes(image_data)

    # save to DB (average of ranges)
    cal_avg = _avg(total.get("calories_min", 0), total.get("calories_max", 0))
    pro_avg = _avg(total.get("protein_min", 0), total.get("protein_max", 0))
    fat_avg = _avg(total.get("fat_min", 0), total.get("fat_max", 0))
    carb_avg = _avg(total.get("carbs_min", 0), total.get("carbs_max", 0))

    meal_log = MealLog(
        user_id=user.id,
        photo_file_id=photo.file_id,
        photo_path=str(photo_path),
        user_comment=message.caption,
        ai_description=json.dumps(parsed, ensure_ascii=False),
        ai_raw_response=raw_response,
        total_calories=cal_avg,
        total_protein=pro_avg,
        total_fat=fat_avg,
        total_carbs=carb_avg,
        is_confirmed=False,
    )
    session.add(meal_log)

    for item in items_data:
        meal_item = MealItem(
            meal_log=meal_log,
            name=item.get("name", "?"),
            calories=_avg(item.get("calories_min", 0), item.get("calories_max", 0)),
            protein=_avg(item.get("protein_min", 0), item.get("protein_max", 0)),
            fat=_avg(item.get("fat_min", 0), item.get("fat_max", 0)),
            carbs=_avg(item.get("carbs_min", 0), item.get("carbs_max", 0)),
            grams=_avg(item.get("grams_min", 0), item.get("grams_max", 0)) or None,
        )
        session.add(meal_item)

    await session.commit()
    await session.refresh(meal_log)

    # format response
    lines = []
    description = parsed.get("description", "")
    if description:
        lines.append(f"\U0001f37d <b>{description}</b>\n")

    # items with ranges
    for item in items_data:
        name = item.get("name", "?")
        g_lo = item.get("grams_min", 0)
        g_hi = item.get("grams_max", 0)
        g_str = f" (~{_range_str(g_lo, g_hi)} \u0433)" if g_hi else ""
        cal_str = _range_str(item.get("calories_min", 0), item.get("calories_max", 0))
        lines.append(f"\u25aa <b>{name}</b>{g_str}")
        lines.append(
            f"   \U0001f4aa {_range_str(item.get('protein_min', 0), item.get('protein_max', 0))} \u0433 | "
            f"\U0001f9c8 {_range_str(item.get('fat_min', 0), item.get('fat_max', 0))} \u0433 | "
            f"\U0001f33e {_range_str(item.get('carbs_min', 0), item.get('carbs_max', 0))} \u0433"
        )
        lines.append(f"   \U0001f525 {cal_str} \u043a\u043a\u0430\u043b")

    # total with ranges
    lines.append("\n\U0001f4ca <b>\u0418\u0442\u043e\u0433\u043e</b>")
    lines.append(format_macros_range(
        total.get("calories_min", 0), total.get("calories_max", 0),
        total.get("protein_min", 0), total.get("protein_max", 0),
        total.get("fat_min", 0), total.get("fat_max", 0),
        total.get("carbs_min", 0), total.get("carbs_max", 0),
    ))

    # main issue
    main_issue = parsed.get("main_issue")
    if main_issue:
        lines.append(f"\n\u26a0\ufe0f <b>Главная проблема:</b> {main_issue}")

    # quick fix
    quick_fix = parsed.get("quick_fix")
    if quick_fix:
        lines.append(f"\n\U0001f4a1 <b>Быстрое решение:</b> {quick_fix}")

    # signals
    signals = parsed.get("signals", [])
    if signals:
        lines.append("")
        for s in signals:
            lines.append(format_signal(s.get("level", "green"), s.get("text", "")))

    # optimization tips
    optimization = parsed.get("optimization", [])
    if optimization:
        lines.append(f"\n\U0001f527 <b>\u041a\u0430\u043a \u0443\u043b\u0443\u0447\u0448\u0438\u0442\u044c:</b>")
        for tip in optimization:
            lines.append(f"\U0001f449 {tip}")

    # day context
    day_ctx = parsed.get("day_context")
    if day_ctx:
        lines.append(f"\n\U0001f4c5 <b>\u041a\u043e\u043d\u0442\u0435\u043a\u0441\u0442 \u0434\u043d\u044f:</b> {day_ctx}")

    # detailed mode extras
    analysis = parsed.get("analysis")
    if analysis:
        lines.append(f"\n\U0001f50d <b>\u0410\u043d\u0430\u043b\u0438\u0437:</b> {analysis}")

    tips = parsed.get("tips")
    if tips:
        lines.append("")
        for tip in tips:
            lines.append(f"\U0001f4a1 {tip}")

    # verdict
    verdict = parsed.get("verdict")
    if verdict:
        lines.append(f"\n\U0001f4ac <b>Вердикт:</b> {verdict}")

    # comparison
    comparison = parsed.get("comparison", [])
    if comparison:
        rating_icons = {
            "fire": "\U0001f525",
            "good": "\u2705",
            "warning": "\u26a0\ufe0f",
            "bad": "\u274c",
        }
        lines.append(f"\n\u2696\ufe0f <b>Сравнение:</b>")
        for c in comparison:
            icon = rating_icons.get(c.get("rating", "good"), "\u2753")
            lines.append(f"{icon} <b>{c.get('variant', '?')}</b> - {c.get('comment', '')}")

    # AI suggestions
    suggestions = parsed.get("suggestions", [])

    await message.answer(
        "\n".join(lines),
        reply_markup=meal_result_keyboard(meal_log.id, suggestions),
        parse_mode="HTML",
    )
