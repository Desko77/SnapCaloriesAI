import asyncio
import json
import logging

from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from bot.config import settings
from bot.handlers import start, photo, history, goal, report, menu, callbacks, text
from bot.middlewares.album import AlbumMiddleware
from bot.middlewares.db import DbSessionMiddleware
from bot.middlewares.user import UserMiddleware
from bot.models.base import async_session
from bot.models.meal import MealLog
from bot.services.embedding import build_meal_text, generate_embedding
from bot.services.vision.factory import create_vision_provider
from bot.services.vision.gemini import GeminiProvider
from bot.services.vision.openai_compat import OpenAICompatProvider

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def _create_local_provider() -> OpenAICompatProvider | None:
    """Create local LM Studio provider if configured."""
    if not settings.local_base_url:
        return None
    return OpenAICompatProvider(
        api_key=settings.local_api_key,
        base_url=settings.local_base_url,
        model=settings.local_model,
        reasoning_effort=settings.local_reasoning_effort,
    )


async def main():
    if not settings.bot_token:
        logger.error("BOT_TOKEN is not set. Set it in .env file.")
        return

    bot = Bot(token=settings.bot_token)
    dp = Dispatcher()

    # vision provider (GPT-4.1 Mini -> Gemini fallback)
    dp["vision_provider"] = create_vision_provider()

    # local model (Gemma 4 via LM Studio) - classifier + text questions
    local = _create_local_provider()

    # topic classifier: local (Gemma) -> Gemini fallback
    if local and await local.is_available():
        dp["topic_classifier"] = local
        logger.info("Topic classifier: local (%s)", settings.local_model)
    else:
        gemini = GeminiProvider()
        dp["topic_classifier"] = gemini if await gemini.is_available() else None
        logger.info("Topic classifier: Gemini (local not configured)")

    # text provider: same as vision (GPT-4.1 Mini) for quality
    # Gemma is only used for classification (fast + free)
    dp["text_provider"] = None  # will fallback to vision_provider in handler

    # middlewares
    dp.update.middleware(DbSessionMiddleware())
    dp.update.middleware(UserMiddleware())

    # album middleware on message level (must be before photo handler)
    dp.message.middleware(AlbumMiddleware())

    # handlers
    dp.include_router(start.router)
    dp.include_router(photo.router)
    dp.include_router(history.router)
    dp.include_router(goal.router)
    dp.include_router(report.router)
    dp.include_router(menu.router)
    dp.include_router(callbacks.router)
    dp.include_router(text.router)  # must be last: catches all text

    # set bot commands menu (russian)
    await bot.set_my_commands([
        BotCommand(command="start", description="Start"),
        BotCommand(command="today", description="Итого за сегодня"),
        BotCommand(command="history", description="История за неделю"),
        BotCommand(command="stats", description="Статистика"),
        BotCommand(command="report", description="AI-анализ за период"),
        BotCommand(command="menu", description="Подбор меню"),
        BotCommand(command="profile", description="Профиль и цели"),
        BotCommand(command="settings", description="Настройки"),
        BotCommand(command="help", description="Справка"),
    ])

    # Background task: retry failed embeddings every 10 minutes
    asyncio.create_task(_backfill_embeddings_loop())

    logger.info("Bot starting...")
    await dp.start_polling(bot)


BACKFILL_INTERVAL = 600  # seconds (10 min)
BACKFILL_BATCH = 20  # meals per cycle


async def _backfill_embeddings_loop() -> None:
    """Periodically generate embeddings for confirmed meals that have none."""
    await asyncio.sleep(30)  # wait for startup
    while True:
        try:
            await _backfill_embeddings_batch()
        except Exception:
            logger.exception("Embedding backfill error")
        await asyncio.sleep(BACKFILL_INTERVAL)


async def _backfill_embeddings_batch() -> None:
    async with async_session() as session:
        result = await session.execute(
            select(MealLog)
            .options(selectinload(MealLog.items))
            .where(
                MealLog.is_confirmed == True,  # noqa: E712
                MealLog.embedding.is_(None),
            )
            .order_by(MealLog.id)
            .limit(BACKFILL_BATCH)
        )
        meals = list(result.scalars().all())
        if not meals:
            return

        filled = 0
        for meal in meals:
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
            embedding = await generate_embedding(build_meal_text(desc, items_data, totals))
            if embedding is not None:
                meal.embedding = embedding
                filled += 1

        await session.commit()
        if filled:
            logger.info("Backfill: generated %d/%d embeddings", filled, len(meals))


if __name__ == "__main__":
    asyncio.run(main())
