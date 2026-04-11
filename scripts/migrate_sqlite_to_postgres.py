"""
Миграция данных из SQLite в PostgreSQL.

Использование:
    uv run python scripts/migrate_sqlite_to_postgres.py \
        --sqlite "sqlite+aiosqlite:///data/snapcalories.db" \
        --postgres "postgresql+asyncpg://snap:snap@localhost:5432/snapcalories"

Предварительно PostgreSQL должен быть запущен (docker compose up -d db).
После миграции запустите: uv run alembic upgrade head
"""
import asyncio
import argparse
import sys

from sqlalchemy import text, insert
from sqlalchemy.ext.asyncio import create_async_engine

# Ensure project root is on sys.path
sys.path.insert(0, ".")

from bot.models.base import Base  # noqa: E402
from bot.models.user import User  # noqa: E402
from bot.models.meal import MealLog, MealItem  # noqa: E402
from bot.models.meal_plan import MealPlan, MealPlanDay  # noqa: E402

# Latest revision from the SQLite migration chain (add_meal_plans)
LATEST_SQLITE_REVISION = "3efd10f009b0"

# Tables in dependency order (parents first)
TABLES_ORDER = [
    ("users", User),
    ("meal_logs", MealLog),
    ("meal_items", MealItem),
    ("meal_plans", MealPlan),
    ("meal_plan_days", MealPlanDay),
]


async def migrate(sqlite_url: str, postgres_url: str) -> None:
    sqlite_engine = create_async_engine(sqlite_url)
    pg_engine = create_async_engine(postgres_url)

    print("1. Creating schema in PostgreSQL...")
    async with pg_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("   Done.")

    print("\n2. Copying data...")
    for table_name, model_class in TABLES_ORDER:
        table = model_class.__table__

        # Read from SQLite
        async with sqlite_engine.connect() as src:
            result = await src.execute(table.select())
            rows = result.mappings().all()

        if not rows:
            print(f"   {table_name}: empty, skipping")
            continue

        # Filter out columns that don't exist in the target (e.g. embedding)
        target_columns = {c.name for c in table.columns}
        cleaned_rows = []
        for r in rows:
            cleaned = {k: v for k, v in dict(r).items() if k in target_columns}
            cleaned_rows.append(cleaned)

        # Write to PostgreSQL in batches
        async with pg_engine.begin() as dst:
            batch_size = 500
            for i in range(0, len(cleaned_rows), batch_size):
                batch = cleaned_rows[i:i + batch_size]
                await dst.execute(insert(table), batch)

        print(f"   {table_name}: {len(rows)} rows")

    print("\n3. Syncing sequences...")
    async with pg_engine.begin() as conn:
        for table_name, _ in TABLES_ORDER:
            try:
                await conn.execute(text(
                    f"SELECT setval(pg_get_serial_sequence('{table_name}', 'id'), "
                    f"COALESCE((SELECT MAX(id) FROM {table_name}), 0))"
                ))
            except Exception as e:
                print(f"   Warning: could not sync sequence for {table_name}: {e}")
    print("   Done.")

    print("\n4. Setting alembic_version...")
    async with pg_engine.begin() as conn:
        await conn.execute(text(
            "CREATE TABLE IF NOT EXISTS alembic_version "
            "(version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
        ))
        await conn.execute(text(
            f"INSERT INTO alembic_version (version_num) "
            f"VALUES ('{LATEST_SQLITE_REVISION}') "
            f"ON CONFLICT DO NOTHING"
        ))
    print(f"   Set to {LATEST_SQLITE_REVISION}")

    await sqlite_engine.dispose()
    await pg_engine.dispose()

    print("\n--- Migration complete! ---")
    print("Next steps:")
    print("  1. Run: uv run alembic upgrade head")
    print("     (applies pgvector + embedding migration)")
    print("  2. Optionally run: uv run python scripts/backfill_embeddings.py")
    print("     (generates embeddings for existing meals)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate data from SQLite to PostgreSQL")
    parser.add_argument(
        "--sqlite",
        default="sqlite+aiosqlite:///data/snapcalories.db",
        help="SQLite connection URL (default: sqlite+aiosqlite:///data/snapcalories.db)",
    )
    parser.add_argument(
        "--postgres",
        required=True,
        help="PostgreSQL connection URL (e.g. postgresql+asyncpg://snap:snap@localhost:5432/snapcalories)",
    )
    args = parser.parse_args()
    asyncio.run(migrate(args.sqlite, args.postgres))
