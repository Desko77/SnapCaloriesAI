import json

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.user import User
from bot.services.stats import get_today_meals, get_today_totals, get_weekly_stats
from bot.utils.formatters import format_macros, format_progress_bar

router = Router()

WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


@router.message(Command("today"))
async def cmd_today(message: Message, session: AsyncSession, user: User):
    totals = await get_today_totals(session, user.id)
    meals = await get_today_meals(session, user.id)

    lines = ["<b>Сегодня:</b>\n"]

    if meals:
        lines.append("<b>Приемы пищи:</b>")
        for m in meals:
            time_str = m.logged_at.strftime("%H:%M")
            desc = m.ai_description
            # try to extract short description
            if desc:
                try:
                    desc = json.loads(desc).get("description", "")
                except Exception:
                    desc = ""
            desc = desc or "Прием пищи"
            lines.append(f"{time_str} - {desc} ({m.total_calories:.0f} ккал)")
        lines.append("")

    lines.append("<b>Итого:</b>")
    lines.append(
        f"Калории: {totals['calories']:.0f} / {user.daily_calories_goal} ккал"
    )
    lines.append(
        f"Белки: {totals['protein']:.0f} / {user.daily_protein_goal} г"
    )
    lines.append(
        f"Жиры: {totals['fat']:.0f} / {user.daily_fat_goal} г"
    )
    lines.append(
        f"Углеводы: {totals['carbs']:.0f} / {user.daily_carbs_goal} г"
    )
    lines.append("")
    lines.append(format_progress_bar(totals["calories"], user.daily_calories_goal))

    if not meals:
        lines.append("\nПока нет сохраненных приемов пищи.")

    await message.answer("\n".join(lines), parse_mode="HTML")


@router.message(Command("history"))
async def cmd_history(message: Message, session: AsyncSession, user: User):
    stats = await get_weekly_stats(session, user.id)

    if stats["days_tracked"] == 0:
        await message.answer("Нет данных за последние 7 дней.")
        return

    lines = ["<b>История за 7 дней:</b>\n"]

    for day_data in stats["daily_breakdown"]:
        day = day_data["day"]
        if hasattr(day, "strftime"):
            day_str = day.strftime("%d.%m")
            wd = WEEKDAYS[day.weekday()]
        else:
            day_str = str(day)
            wd = ""
        cal = day_data["calories"]
        lines.append(f"{wd} {day_str}: {cal:.0f} ккал")

    lines.append(f"\nДней с данными: {stats['days_tracked']}")

    await message.answer("\n".join(lines), parse_mode="HTML")


@router.message(Command("stats"))
async def cmd_stats(message: Message, session: AsyncSession, user: User):
    stats = await get_weekly_stats(session, user.id)

    if stats["days_tracked"] == 0:
        await message.answer("Нет данных для статистики.")
        return

    lines = ["<b>Статистика за 7 дней:</b>\n"]
    lines.append("<b>Среднее в день:</b>")
    lines.append(format_macros(
        stats["avg_calories"], stats["avg_protein"],
        stats["avg_fat"], stats["avg_carbs"],
    ))
    lines.append(f"\nДней отслежено: {stats['days_tracked']}")

    # compare with goals
    cal_pct = int(stats["avg_calories"] / user.daily_calories_goal * 100) if user.daily_calories_goal else 0
    lines.append(f"Среднее от цели по калориям: {cal_pct}%")

    await message.answer("\n".join(lines), parse_mode="HTML")
