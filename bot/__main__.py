import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand

from bot.config import settings
from bot.handlers import start, photo, history, goal, report, callbacks
from bot.middlewares.db import DbSessionMiddleware
from bot.middlewares.user import UserMiddleware
from bot.services.vision.factory import create_vision_provider

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def main():
    if not settings.bot_token:
        logger.error("BOT_TOKEN is not set. Set it in .env file.")
        return

    bot = Bot(token=settings.bot_token)
    dp = Dispatcher()

    # vision provider singleton
    dp["vision_provider"] = create_vision_provider()

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

    # set bot commands menu (russian)
    await bot.set_my_commands([
        BotCommand(command="start", description="Start"),
        BotCommand(command="today", description="Итого за сегодня"),
        BotCommand(command="history", description="История за неделю"),
        BotCommand(command="stats", description="Статистика"),
        BotCommand(command="report", description="AI-анализ за период"),
        BotCommand(command="goal", description="Цели и параметры"),
        BotCommand(command="settings", description="Настройки"),
        BotCommand(command="help", description="Справка"),
    ])

    logger.info("Bot starting...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
