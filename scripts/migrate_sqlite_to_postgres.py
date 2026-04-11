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
        # pgvector extension must be enabled BEFORE create_all,
        # because MealLog model has Vector(768) column
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
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

        # Filter out columns that don't exist in source (e.g. embedding)
        source_keys = set(dict(rows[0]).keys())
        cleaned_rows = []
        for r in rows:
            cleaned = {k: v for k, v in dict(r).items() if k in source_keys}
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

    print("\n4. Verifying data integrity...")
    async with sqlite_engine.connect() as src, pg_engine.connect() as dst:
        all_ok = True
        for table_name, model_class in TABLES_ORDER:
            src_count = (await src.execute(text(f"SELECT COUNT(*) FROM {table_name}"))).scalar()
            dst_count = (await dst.execute(text(f"SELECT COUNT(*) FROM {table_name}"))).scalar()
            status = "OK" if src_count == dst_count else "MISMATCH!"
            if src_count != dst_count:
                all_ok = False
            print(f"   {table_name}: SQLite={src_count}, PostgreSQL={dst_count} [{status}]")
        if not all_ok:
            print("\n   WARNING: Row counts don't match! Check data manually.")

    print("\n5. Setting alembic_version...")
    async with pg_engine.begin() as conn:
        # Set to HEAD (a1b2c3d4e5f6) since create_all already created
        # the embedding column. alembic upgrade head will be a no-op.
        head_revision = "a1b2c3d4e5f6"
        await conn.execute(text(
            "CREATE TABLE IF NOT EXISTS alembic_version "
            "(version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
        ))
        await conn.execute(text("DELETE FROM alembic_version"))
        await conn.execute(text(
            f"INSERT INTO alembic_version (version_num) VALUES ('{head_revision}')"
        ))
    print(f"   Set to {head_revision} (HEAD)")

    await sqlite_engine.dispose()
    await pg_engine.dispose()

    print("\n--- Migration complete! ---")
    print("Next steps:")
    print("  1. Update DATABASE_URL in .env to PostgreSQL URL")
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
