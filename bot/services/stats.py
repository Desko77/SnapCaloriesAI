import json
from collections import Counter
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bot.models.meal import MealLog


async def get_today_totals(
    session: AsyncSession, user_id: int, day: date | None = None
) -> dict[str, float]:
    day = day or date.today()

    result = await session.execute(
        select(
            func.coalesce(func.sum(MealLog.total_calories), 0),
            func.coalesce(func.sum(MealLog.total_protein), 0),
            func.coalesce(func.sum(MealLog.total_fat), 0),
            func.coalesce(func.sum(MealLog.total_carbs), 0),
        ).where(
            MealLog.user_id == user_id,
            MealLog.is_confirmed == True,  # noqa: E712
            func.date(MealLog.logged_at) == day,
        )
    )
    row = result.one()
    return {
        "calories": row[0],
        "protein": row[1],
        "fat": row[2],
        "carbs": row[3],
    }


async def get_today_meals(
    session: AsyncSession, user_id: int, day: date | None = None
) -> list[MealLog]:
    day = day or date.today()

    result = await session.execute(
        select(MealLog)
        .where(
            MealLog.user_id == user_id,
            MealLog.is_confirmed == True,  # noqa: E712
            func.date(MealLog.logged_at) == day,
        )
        .order_by(MealLog.logged_at)
    )
    return list(result.scalars().all())


async def get_period_stats(
    session: AsyncSession, user_id: int, days: int = 7
) -> dict[str, Any]:
    since = date.today() - timedelta(days=days - 1)

    result = await session.execute(
        select(
            func.date(MealLog.logged_at).label("day"),
            func.sum(MealLog.total_calories),
            func.sum(MealLog.total_protein),
            func.sum(MealLog.total_fat),
            func.sum(MealLog.total_carbs),
        )
        .where(
            MealLog.user_id == user_id,
            MealLog.is_confirmed == True,  # noqa: E712
            func.date(MealLog.logged_at) >= since,
        )
        .group_by(func.date(MealLog.logged_at))
        .order_by(func.date(MealLog.logged_at))
    )
    rows = result.all()

    if not rows:
        return {
            "avg_calories": 0, "avg_protein": 0,
            "avg_fat": 0, "avg_carbs": 0,
            "days_tracked": 0, "daily_breakdown": [],
        }

    daily = [
        {"day": r[0], "calories": r[1], "protein": r[2], "fat": r[3], "carbs": r[4]}
        for r in rows
    ]
    n = len(rows)
    return {
        "avg_calories": sum(d["calories"] for d in daily) / n,
        "avg_protein": sum(d["protein"] for d in daily) / n,
        "avg_fat": sum(d["fat"] for d in daily) / n,
        "avg_carbs": sum(d["carbs"] for d in daily) / n,
        "days_tracked": n,
        "daily_breakdown": daily,
    }


async def get_weekly_stats(
    session: AsyncSession, user_id: int
) -> dict[str, Any]:
    return await get_period_stats(session, user_id, days=7)


async def get_period_meals_for_prompt(
    session: AsyncSession, user_id: int, days: int = 7
) -> tuple[list[dict], list[str]]:
    """Get all meals for a period, formatted for AI prompt. Returns (meals, frequent_products)."""
    since = date.today() - timedelta(days=days - 1)

    result = await session.execute(
        select(MealLog)
        .options(selectinload(MealLog.items))
        .where(
            MealLog.user_id == user_id,
            MealLog.is_confirmed == True,  # noqa: E712
            func.date(MealLog.logged_at) >= since,
        )
        .order_by(MealLog.logged_at)
    )
    raw_meals = list(result.scalars().all())

    meals = []
    product_counter: Counter[str] = Counter()
    for meal in raw_meals:
        desc = ""
        if meal.ai_description:
            try:
                desc = json.loads(meal.ai_description).get("description", "")
            except (json.JSONDecodeError, AttributeError):
                pass
        desc = desc or meal.user_comment or "Прием пищи"

        meals.append({
            "date": meal.logged_at.strftime("%d.%m"),
            "time": meal.logged_at.strftime("%H:%M"),
            "description": desc,
            "calories": int(meal.total_calories),
            "protein": int(meal.total_protein),
            "fat": int(meal.total_fat),
            "carbs": int(meal.total_carbs),
        })
        for item in meal.items:
            product_counter[item.name] += 1

    frequent = [name for name, count in product_counter.most_common(10) if count >= 2]
    return meals, frequent


async def get_weekly_summary_for_prompt(
    session: AsyncSession, user_id: int
) -> dict[str, Any] | None:
    """Build a compact weekly summary for AI prompt context."""
    stats = await get_weekly_stats(session, user_id)
    if stats["days_tracked"] == 0:
        return None

    # get all confirmed meals for the week to extract product names
    since = date.today() - timedelta(days=6)
    result = await session.execute(
        select(MealLog)
        .options(selectinload(MealLog.items))
        .where(
            MealLog.user_id == user_id,
            MealLog.is_confirmed == True,  # noqa: E712
            func.date(MealLog.logged_at) >= since,
        )
    )
    meals = list(result.scalars().all())

    # count frequent products
    product_counter: Counter[str] = Counter()
    for meal in meals:
        for item in meal.items:
            product_counter[item.name] += 1

    frequent = [name for name, count in product_counter.most_common(8) if count >= 2]

    # detect patterns
    patterns = []
    avg_fat = stats["avg_fat"]
    avg_protein = stats["avg_protein"]
    if avg_fat > 60:
        patterns.append("среднее потребление жиров выше нормы")
    if avg_protein < 80:
        patterns.append("среднее потребление белка ниже рекомендуемого")

    # check if multiple high-fat items often appear together
    high_fat_combos = 0
    for meal in meals:
        fat_items = [i for i in meal.items if i.fat > 10]
        if len(fat_items) >= 2:
            high_fat_combos += 1
    if high_fat_combos >= 3:
        patterns.append("часто сочетает несколько жирных продуктов в одном приеме")

    return {
        "avg_calories": int(stats["avg_calories"]),
        "avg_protein": int(stats["avg_protein"]),
        "avg_fat": int(stats["avg_fat"]),
        "avg_carbs": int(stats["avg_carbs"]),
        "days_tracked": stats["days_tracked"],
        "frequent_products": frequent,
        "patterns": patterns,
    }


def format_today_meals_for_prompt(meals: list[MealLog]) -> list[dict[str, Any]]:
    """Format today's meals as compact dicts for the prompt."""
    result = []
    for meal in meals:
        # extract short description from ai_description JSON
        desc = ""
        if meal.ai_description:
            try:
                desc = json.loads(meal.ai_description).get("description", "")
            except (json.JSONDecodeError, AttributeError):
                pass
        desc = desc or meal.user_comment or "Прием пищи"

        # extract item names from ai_description
        items_str = ""
        if meal.ai_description:
            try:
                parsed = json.loads(meal.ai_description)
                item_names = [it.get("name", "") for it in parsed.get("items", [])]
                items_str = ", ".join(n for n in item_names if n)
            except (json.JSONDecodeError, AttributeError):
                pass

        result.append({
            "time": meal.logged_at.strftime("%H:%M"),
            "description": desc,
            "items": items_str,
            "calories": int(meal.total_calories),
            "protein": int(meal.total_protein),
            "fat": int(meal.total_fat),
            "carbs": int(meal.total_carbs),
        })
    return result
