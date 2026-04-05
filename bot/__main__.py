import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand

from bot.config import settings
from bot.handlers import start, photo, history, goal, report, callbacks, text
from bot.middlewares.db import DbSessionMiddleware
from bot.middlewares.user import UserMiddleware
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

    # handlers
    dp.include_router(start.router)
    dp.include_router(photo.router)
    dp.include_router(history.router)
    dp.include_router(goal.router)
    dp.include_router(report.router)
    dp.include_router(callbacks.router)
    dp.include_router(text.router)  # must be last: catches all text

    # set bot commands menu (russian)
    await bot.set_my_commands([
        BotCommand(command="start", description="Start"),
        BotCommand(command="today", description="Итого за сегодня"),
        BotCommand(command="history", description="История за неделю"),
        BotCommand(command="stats", description="Статистика"),
        BotCommand(command="report", description="AI-анализ за период"),
        BotCommand(command="profile", description="Профиль и цели"),
        BotCommand(command="settings", description="Настройки"),
        BotCommand(command="help", description="Справка"),
    ])

    logger.info("Bot starting...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
