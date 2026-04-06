"""Meal plan storage, retrieval and comparison."""

import json
from datetime import date, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bot.models.meal_plan import MealPlan, MealPlanDay


async def save_meal_plan(
    session: AsyncSession,
    user_id: int,
    period_type: str,
    start_date: date,
    end_date: date,
    parsed_json: dict,
    raw_response: str,
) -> MealPlan:
    """Save a new meal plan, deactivating any existing active plan."""
    # deactivate old plans
    await session.execute(
        update(MealPlan)
        .where(MealPlan.user_id == user_id, MealPlan.is_active == True)  # noqa: E712
        .values(is_active=False)
    )

    plan = MealPlan(
        user_id=user_id,
        period_type=period_type,
        start_date=start_date,
        end_date=end_date,
        raw_response=raw_response,
        is_active=True,
    )
    session.add(plan)

    # create per-day rows
    days_data = parsed_json.get("days", [])
    current = start_date
    for i, day_data in enumerate(days_data):
        if current > end_date:
            break
        total = day_data.get("total", {})
        plan_day = MealPlanDay(
            plan=plan,
            day_date=current,
            calories=total.get("calories", 0),
            protein=total.get("protein", 0),
            fat=total.get("fat", 0),
            carbs=total.get("carbs", 0),
            meals_json=json.dumps(day_data.get("meals", []), ensure_ascii=False),
        )
        session.add(plan_day)
        current += timedelta(days=1)

    await session.commit()
    await session.refresh(plan)
    return plan


async def get_active_plan(
    session: AsyncSession, user_id: int
) -> MealPlan | None:
    """Get the active meal plan with all days eagerly loaded."""
    result = await session.execute(
        select(MealPlan)
        .options(selectinload(MealPlan.days))
        .where(MealPlan.user_id == user_id, MealPlan.is_active == True)  # noqa: E712
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_plan_day(
    session: AsyncSession, user_id: int, day: date | None = None
) -> MealPlanDay | None:
    """Get the plan day for a specific date from the active plan."""
    day = day or date.today()
    result = await session.execute(
        select(MealPlanDay)
        .join(MealPlan)
        .where(
            MealPlan.user_id == user_id,
            MealPlan.is_active == True,  # noqa: E712
            MealPlanDay.day_date == day,
        )
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_plan_for_period(
    session: AsyncSession, user_id: int, start: date, end: date
) -> list[MealPlanDay]:
    """Get all plan days within a date range from the active plan."""
    result = await session.execute(
        select(MealPlanDay)
        .join(MealPlan)
        .where(
            MealPlan.user_id == user_id,
            MealPlan.is_active == True,  # noqa: E712
            MealPlanDay.day_date >= start,
            MealPlanDay.day_date <= end,
        )
        .order_by(MealPlanDay.day_date)
    )
    return list(result.scalars().all())


def compare_day(planned: MealPlanDay, actual: dict) -> dict:
    """Compare planned vs actual KBJU for a single day.

    Returns dict with planned, actual, diff, pct, matched per metric,
    and overall_matched (all within +-10%).
    """
    metrics = ["calories", "protein", "fat", "carbs"]
    p = {m: getattr(planned, m, 0) for m in metrics}
    a = {m: actual.get(m, 0) for m in metrics}

    diff = {}
    pct = {}
    matched = {}

    for m in metrics:
        diff[m] = a[m] - p[m]
        if p[m] > 0:
            pct[m] = round(a[m] / p[m] * 100, 1)
            matched[m] = abs(diff[m]) / p[m] <= 0.10
        else:
            pct[m] = 0 if a[m] == 0 else 999
            matched[m] = a[m] == 0

    return {
        "has_plan": True,
        "planned": p,
        "actual": a,
        "diff": diff,
        "pct": pct,
        "matched": matched,
        "overall_matched": all(matched.values()),
    }


def compare_period(
    plan_days: list[MealPlanDay],
    daily_breakdown: list[dict],
) -> dict | None:
    """Compare plan vs actual across a period.

    daily_breakdown: list of {day: date, calories, protein, fat, carbs}.
    Returns summary dict or None if no overlap.
    """
    if not plan_days:
        return None

    # index plan days by date
    plan_by_date = {pd.day_date: pd for pd in plan_days}

    # index actual by date
    actual_by_date = {}
    for d in daily_breakdown:
        day = d["day"]
        if hasattr(day, "isoformat"):
            actual_by_date[day] = d
        else:
            actual_by_date[str(day)] = d

    comparisons = []
    for day_date, planned in plan_by_date.items():
        actual = actual_by_date.get(day_date)
        if actual:
            comparisons.append(compare_day(planned, actual))

    if not comparisons:
        return None

    days_matched = sum(1 for c in comparisons if c["overall_matched"])
    total_days = len(plan_by_date)
    days_with_data = len(comparisons)

    # average deviations
    avg_diff = {}
    for m in ["calories", "protein", "fat", "carbs"]:
        avg_diff[m] = round(sum(c["diff"][m] for c in comparisons) / days_with_data, 1)

    adherence = round(days_matched / days_with_data * 100) if days_with_data else 0

    return {
        "total_days": total_days,
        "days_with_data": days_with_data,
        "days_matched": days_matched,
        "avg_diff": avg_diff,
        "adherence_pct": adherence,
    }
