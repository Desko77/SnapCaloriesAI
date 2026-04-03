from aiogram import Router
from aiogram.filters import CommandStart, Command
from aiogram.types import Message

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message):
    name = message.from_user.first_name or "друг"
    await message.answer(
        f"Привет, {name}!\n\n"
        "<b>SnapCaloriesAI</b> - твой персональный AI-нутрициолог.\n\n"
        "Просто отправь фото еды - я распознаю продукты, "
        "рассчитаю калории, белки, жиры и углеводы, "
        "подскажу что можно улучшить и помогу достичь твоей цели.\n\n"
        "Можешь добавить подпись к фото - например, "
        '"это творог, а не сыр" - и я учту.\n\n'
        "<b>Команды:</b>\n"
        "/today - что съедено сегодня\n"
        "/history - история за неделю\n"
        "/stats - статистика\n"
        "/report - AI-анализ питания за период\n"
        "/profile - профиль и цели\n"
        "/settings - настройки\n"
        "/help - справка",
        parse_mode="HTML",
    )


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "<b>Как пользоваться:</b>\n\n"
        "1. Отправь фото еды (можно с подписью-уточнением)\n"
        "2. Я распознаю продукты и покажу КБЖУ с диапазонами\n"
        "3. Если ошибся - нажми «Уточнить» и напиши что исправить\n"
        "4. Нажми «Сохранить» - прием пищи запомнится\n\n"
        "<b>Что умею:</b>\n"
        "- Анализ фото еды с детализацией по продуктам\n"
        "- Советы по оптимизации блюда\n"
        "- Предложения меню на оставшийся бюджет КБЖУ\n"
        "- Поиск более здоровых альтернатив\n"
        "- Отслеживание прогресса к цели\n"
        "- AI-отчет с анализом паттернов питания",
        parse_mode="HTML",
    )
