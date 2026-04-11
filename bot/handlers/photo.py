import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path

from aiogram import Bot, Router, F
from aiogram.enums import ChatAction
from aiogram.filters import StateFilter
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import now_local
from bot.keyboards.meal import meal_result_keyboard
from bot.models.meal import MealLog, MealItem
from bot.models.user import User
from bot.services.nutrition import parse_ai_response
from bot.services.prompts import render_prompt
from bot.services.embedding import build_meal_text, generate_embedding
from bot.services.stats import (
    get_today_meals,
    get_today_totals,
    get_weekly_summary_for_prompt,
    format_today_meals_for_prompt,
    get_last_meal,
)
from bot.services.vision.base import VisionProvider
from bot.utils.formatters import format_macros_range, format_signal

logger = logging.getLogger(__name__)

from bot.constants import GOAL_TYPE_LABELS

router = Router()

ADD_TO_MEAL_PROMPT = (
    "Пользователь отправил фото еды с подписью: \"{caption}\"\n"
    "Хочет ли пользователь ДОБАВИТЬ эту еду к уже существующему приему пищи "
    "(завтраку, обеду, ужину, перекусу)?\n"
    "Ответь ОДНИМ словом: YES или NO"
)


def _avg(lo, hi):
    return (lo + hi) / 2


def _range_str(lo, hi):
    if lo == hi:
        return str(int(lo))
    return f"{int(lo)}-{int(hi)}"


async def _is_add_to_meal(classifier: VisionProvider | None, caption: str) -> bool:
    """Semantically detect if caption means 'add to existing meal'."""
    if classifier is None or not caption:
        return False
    try:
        response = await classifier.analyze(
            None, ADD_TO_MEAL_PROMPT.format(caption=caption[:200])
        )
        return "YES" in response.strip().upper()
    except Exception:
        logger.warning("Add-to-meal classifier failed, treating as new meal")
        return False


async def _download_album_photos(
    bot: Bot, messages: list[Message]
) -> list[tuple[bytes, str]]:
    """Download photos from album messages. Returns [(image_data, file_id), ...]."""
    results = []
    for msg in messages:
        if not msg.photo:
            continue
        photo = msg.photo[-1]
        file = await bot.get_file(photo.file_id)
        bio = await bot.download_file(file.file_path)
        results.append((bio.read(), photo.file_id))
    return results


async def _save_photos_to_disk(
    photos: list[tuple[bytes, str]], telegram_id: int
) -> list[str]:
    """Save photo bytes to disk. Returns list of file paths."""
    photos_dir = Path("data/photos") / str(telegram_id)
    photos_dir.mkdir(parents=True, exist_ok=True)

    ts = now_local().strftime("%Y%m%d_%H%M%S")
    paths = []
    for i, (image_data, _) in enumerate(photos):
        suffix = f"_{i}" if i > 0 else ""
        path = photos_dir / f"{ts}{suffix}.jpg"
        await asyncio.to_thread(path.write_bytes, image_data)
        paths.append(str(path))
    return paths


def _build_new_items(items_data: list[dict]) -> list[MealItem]:
    """Create MealItem objects from parsed AI items."""
    result = []
    for item in items_data:
        result.append(MealItem(
            name=item.get("name", "?"),
            calories=_avg(item.get("calories_min", 0), item.get("calories_max", 0)),
            protein=_avg(item.get("protein_min", 0), item.get("protein_max", 0)),
            fat=_avg(item.get("fat_min", 0), item.get("fat_max", 0)),
            carbs=_avg(item.get("carbs_min", 0), item.get("carbs_max", 0)),
            grams=_avg(item.get("grams_min", 0), item.get("grams_max", 0)) or None,
        ))
    return result


def _format_new_meal_response(parsed: dict, items_data: list[dict]) -> list[str]:
    """Format the standard response for a new/standalone meal analysis."""
    lines = []
    description = parsed.get("description", "")
    if description:
        lines.append(f"\U0001f37d <b>{description}</b>\n")

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

    total = parsed["total"]
    lines.append("\n\U0001f4ca <b>\u0418\u0442\u043e\u0433\u043e</b>")
    lines.append(format_macros_range(
        total.get("calories_min", 0), total.get("calories_max", 0),
        total.get("protein_min", 0), total.get("protein_max", 0),
        total.get("fat_min", 0), total.get("fat_max", 0),
        total.get("carbs_min", 0), total.get("carbs_max", 0),
    ))

    main_issue = parsed.get("main_issue")
    if main_issue:
        lines.append(f"\n\u274c <b>Вывод:</b> {main_issue}")

    quick_fix = parsed.get("quick_fix")
    if quick_fix:
        lines.append(f"\n\U0001f527 <b>Как сделать идеально (1 замена):</b>\n\U0001f449 {quick_fix}")

    signals = parsed.get("signals", [])
    if signals:
        lines.append("")
        for s in signals:
            lines.append(format_signal(s.get("level", "green"), s.get("text", "")))

    optimization = parsed.get("optimization", [])
    if optimization:
        lines.append(f"\n\U0001f527 <b>\u041a\u0430\u043a \u0443\u043b\u0443\u0447\u0448\u0438\u0442\u044c:</b>")
        for tip in optimization:
            lines.append(f"\U0001f449 {tip}")

    day_ctx = parsed.get("day_context")
    if day_ctx:
        lines.append(f"\n\U0001f4c5 <b>\u041a\u043e\u043d\u0442\u0435\u043a\u0441\u0442 \u0434\u043d\u044f:</b> {day_ctx}")

    analysis = parsed.get("analysis")
    if analysis:
        lines.append(f"\n\U0001f50d <b>\u0410\u043d\u0430\u043b\u0438\u0437:</b> {analysis}")

    tips = parsed.get("tips")
    if tips:
        lines.append("")
        for tip in tips:
            lines.append(f"\U0001f4a1 {tip}")

    verdict = parsed.get("verdict")
    if verdict:
        lines.append(f"\n\U0001f4ac <b>Вердикт:</b> {verdict}")

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

    return lines


@router.message(F.photo, StateFilter(None))
async def handle_photo(
    message: Message,
    bot: Bot,
    session: AsyncSession,
    user: User,
    vision_provider: VisionProvider,
    topic_classifier: VisionProvider | None = None,
    album: list[Message] | None = None,
):
    await bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)

    # --- collect photos: album (media group) or single ---
    photo_messages = album if album else [message]
    caption = photo_messages[0].caption  # Telegram puts caption on first photo

    # download all photos
    photos = await _download_album_photos(bot, photo_messages)
    if not photos:
        await message.answer("Не удалось загрузить фото. Попробуйте еще раз.")
        return

    image_data_list = [data for data, _ in photos]

    # --- detect "add to existing meal" intent ---
    is_addition = await _is_add_to_meal(topic_classifier, caption)

    # --- build AI context ---
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

    # multi-photo hint for AI
    comment_parts = []
    if caption:
        comment_parts.append(caption)
    if len(photos) > 1:
        comment_parts.append(
            f"\n[Приложено {len(photos)} фото - это ОДИН прием пищи. "
            f"Распознай ВСЕ продукты со ВСЕХ фотографий.]"
        )

    prompt = render_prompt(
        "analyze_photo.j2",
        user_comment="\n".join(comment_parts) if comment_parts else None,
        user_profile=user_profile,
        user_goals=user_goals,
        today_totals=today_totals,
        today_meals=today_meals,
        weekly_summary=weekly_summary,
        response_mode=user.response_mode,
    )

    # --- call AI ---
    ai_input = image_data_list if len(image_data_list) > 1 else image_data_list[0]
    try:
        raw_response = await vision_provider.analyze(ai_input, prompt)
        parsed = parse_ai_response(raw_response)
    except json.JSONDecodeError:
        logger.exception("Failed to parse AI response")
        await message.answer("AI вернул неожиданный формат. Попробуйте еще раз.")
        return
    except Exception:
        logger.exception("Vision provider error")
        await message.answer("AI-сервис недоступен. Попробуйте позже.")
        return

    try:
        items_data = parsed["items"]
        total = parsed["total"]
    except KeyError:
        logger.error("AI response missing required keys: %s", parsed)
        await message.answer("AI вернул неполный ответ. Попробуйте еще раз.")
        return

    # --- save photos to disk ---
    photo_paths = await _save_photos_to_disk(photos, user.telegram_id)

    # --- calculate averages ---
    cal_avg = _avg(total.get("calories_min", 0), total.get("calories_max", 0))
    pro_avg = _avg(total.get("protein_min", 0), total.get("protein_max", 0))
    fat_avg = _avg(total.get("fat_min", 0), total.get("fat_max", 0))
    carb_avg = _avg(total.get("carbs_min", 0), total.get("carbs_max", 0))

    new_items = _build_new_items(items_data)

    # --- ADD TO EXISTING MEAL ---
    if is_addition:
        existing_meal = await get_last_meal(session, user.id)
        if existing_meal:
            # parse existing ai_description once
            old_desc = ""
            try:
                merged = json.loads(existing_meal.ai_description) if existing_meal.ai_description else {}
                old_desc = merged.get("description", "")
            except (json.JSONDecodeError, TypeError):
                merged = {}

            # add new items to DB
            for mi in new_items:
                mi.meal_log_id = existing_meal.id
                session.add(mi)

            # update totals
            existing_meal.total_calories += cal_avg
            existing_meal.total_protein += pro_avg
            existing_meal.total_fat += fat_avg
            existing_meal.total_carbs += carb_avg

            # append photo paths
            if existing_meal.photo_path and photo_paths:
                existing_meal.photo_path += "," + ",".join(photo_paths)
            elif photo_paths:
                existing_meal.photo_path = ",".join(photo_paths)

            # merge ai_description: append new items, sum min/max ranges
            old_total = merged.get("total", {})
            merged.setdefault("items", []).extend(items_data)
            merged["total"] = {
                "calories_min": old_total.get("calories_min", 0) + total.get("calories_min", 0),
                "calories_max": old_total.get("calories_max", 0) + total.get("calories_max", 0),
                "protein_min": old_total.get("protein_min", 0) + total.get("protein_min", 0),
                "protein_max": old_total.get("protein_max", 0) + total.get("protein_max", 0),
                "fat_min": old_total.get("fat_min", 0) + total.get("fat_min", 0),
                "fat_max": old_total.get("fat_max", 0) + total.get("fat_max", 0),
                "carbs_min": old_total.get("carbs_min", 0) + total.get("carbs_min", 0),
                "carbs_max": old_total.get("carbs_max", 0) + total.get("carbs_max", 0),
            }
            existing_meal.ai_description = json.dumps(merged, ensure_ascii=False)

            # Regenerate embedding with updated meal data
            try:
                emb_desc = merged.get("description", "") or caption or "Прием пищи"
                emb_totals = {
                    "calories": existing_meal.total_calories,
                    "protein": existing_meal.total_protein,
                    "fat": existing_meal.total_fat,
                    "carbs": existing_meal.total_carbs,
                }
                all_items = merged.get("items", [])
                emb_text = build_meal_text(emb_desc, all_items, emb_totals)
                existing_meal.embedding = await generate_embedding(emb_text)
            except Exception:
                logger.warning("Failed to regenerate embedding for meal %d", existing_meal.id)

            await session.commit()
            await session.refresh(existing_meal)

            # --- format "added" response ---
            lines = []
            prefix = f" ({old_desc})" if old_desc else ""
            lines.append(f"\u2795 <b>Добавлено к приему{prefix}:</b>\n")

            for item in items_data:
                name = item.get("name", "?")
                g_lo = item.get("grams_min", 0)
                g_hi = item.get("grams_max", 0)
                g_str = f" (~{_range_str(g_lo, g_hi)} \u0433)" if g_hi else ""
                cal_str = _range_str(
                    item.get("calories_min", 0), item.get("calories_max", 0)
                )
                lines.append(f"\u25aa <b>{name}</b>{g_str}")
                lines.append(
                    f"   \U0001f4aa {_range_str(item.get('protein_min', 0), item.get('protein_max', 0))} \u0433 | "
                    f"\U0001f9c8 {_range_str(item.get('fat_min', 0), item.get('fat_max', 0))} \u0433 | "
                    f"\U0001f33e {_range_str(item.get('carbs_min', 0), item.get('carbs_max', 0))} \u0433"
                )
                lines.append(f"   \U0001f525 {cal_str} \u043a\u043a\u0430\u043b")

            lines.append(f"\n\U0001f4ca <b>\u041e\u0431\u043d\u043e\u0432\u043b\u0435\u043d\u043d\u044b\u0439 \u0438\u0442\u043e\u0433 \u043f\u0440\u0438\u0435\u043c\u0430:</b>")
            lines.append(
                f"\U0001f525 {int(existing_meal.total_calories)} \u043a\u043a\u0430\u043b | "
                f"\U0001f4aa {int(existing_meal.total_protein)} \u0433 | "
                f"\U0001f9c8 {int(existing_meal.total_fat)} \u0433 | "
                f"\U0001f33e {int(existing_meal.total_carbs)} \u0433"
            )

            await message.answer(
                "\n".join(lines),
                reply_markup=meal_result_keyboard(existing_meal.id),
                parse_mode="HTML",
            )
            return
        # no existing meal found - fall through to create new

    # --- CREATE NEW MEAL ---
    meal_log = MealLog(
        user_id=user.id,
        photo_file_id=photos[0][1],
        photo_path=",".join(photo_paths),
        user_comment=caption,
        ai_description=json.dumps(parsed, ensure_ascii=False),
        ai_raw_response=raw_response,
        total_calories=cal_avg,
        total_protein=pro_avg,
        total_fat=fat_avg,
        total_carbs=carb_avg,
        is_confirmed=False,
    )
    session.add(meal_log)

    for mi in new_items:
        mi.meal_log = meal_log
        session.add(mi)

    await session.commit()
    await session.refresh(meal_log)

    # --- format response ---
    lines = _format_new_meal_response(parsed, items_data)
    suggestions = parsed.get("suggestions", [])

    await message.answer(
        "\n".join(lines),
        reply_markup=meal_result_keyboard(meal_log.id, suggestions),
        parse_mode="HTML",
    )
