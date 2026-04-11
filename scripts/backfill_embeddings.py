"""
Генерация эмбеддингов для приёмов пищи, у которых embedding = NULL.

Использование:
    uv run python scripts/backfill_embeddings.py

Требует запущенного PostgreSQL с примененными миграциями (alembic upgrade head).
"""
import asyncio
import json
import sys

from sqlalchemy import select
from sqlalchemy.orm import selectinload

# Ensure project root is on sys.path
sys.path.insert(0, ".")

from bot.models.base import async_session  # noqa: E402
from bot.models.meal import MealLog  # noqa: E402
from bot.services.embedding import generate_embedding, build_meal_text  # noqa: E402


async def backfill() -> None:
    async with async_session() as session:
        # Find all confirmed meals without an embedding
        result = await session.execute(
            select(MealLog)
            .options(selectinload(MealLog.items))
            .where(
                MealLog.is_confirmed == True,  # noqa: E712
                MealLog.embedding.is_(None),
            )
            .order_by(MealLog.id)
        )
        meals = list(result.scalars().all())
        total = len(meals)
        print(f"Found {total} meals without embeddings")

        if not total:
            return

        success = 0
        failed = 0

        for i, meal in enumerate(meals, 1):
            # Extract description from ai_description JSON
            desc = ""
            items_data = []
            if meal.ai_description:
                try:
                    parsed = json.loads(meal.ai_description)
                    desc = parsed.get("description", "")
                    items_data = parsed.get("items", [])
                except (json.JSONDecodeError, AttributeError):
                    pass
            desc = desc or meal.user_comment or "Прием пищи"

            totals = {
                "calories": meal.total_calories,
                "protein": meal.total_protein,
                "fat": meal.total_fat,
                "carbs": meal.total_carbs,
            }

            text = build_meal_text(desc, items_data, totals)
            embedding = await generate_embedding(text)

            if embedding is not None:
                meal.embedding = embedding
                success += 1
            else:
                failed += 1

            # Commit in batches and print progress
            if i % 50 == 0 or i == total:
                await session.commit()
                print(f"  Progress: {i}/{total} (ok: {success}, failed: {failed})")

        await session.commit()
        print(f"\nDone! Processed: {total}, success: {success}, failed: {failed}")


if __name__ == "__main__":
    asyncio.run(backfill())
