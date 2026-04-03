from aiogram import Router
from aiogram.filters import CommandStart, Command
from aiogram.types import Message

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(
        "SnapCaloriesAI - бот для расчета КБЖУ по фото.\n\n"
        "Отправь фото еды, и я рассчитаю калории, белки, жиры и углеводы.\n\n"
        "Команды:\n"
        "/today - итого за сегодня\n"
        "/history - история за неделю\n"
        "/stats - статистика\n"
        "/report - AI-анализ за период\n"
        "/goal - цели и параметры\n"
        "/settings - настройки\n"
        "/help - справка"
    )


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "Как пользоваться:\n\n"
        "1. Отправь фото еды (можно с подписью)\n"
        "2. Бот распознает продукты и рассчитает КБЖУ\n"
        "3. Уточни, если бот ошибся\n"
        "4. Сохрани результат\n\n"
        "Бот запоминает все приемы пищи и показывает статистику."
    )
