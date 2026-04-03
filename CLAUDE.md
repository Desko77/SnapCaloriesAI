# SnapCaloriesAI

Telegram-бот для расчета КБЖУ по фотографиям еды с AI-анализом.

## Стек

- Python 3.12+, aiogram 3.x (async Telegram bot framework)
- SQLAlchemy 2.0 + aiosqlite (SQLite, файл на хосте)
- Google Gemini / OpenAI-совместимый API (LM Studio, Ollama, Qwen)
- Jinja2 (шаблоны промптов), pydantic-settings (конфиг)
- Docker (один контейнер, БД на хосте через bind mount)
- uv (менеджер зависимостей)

## Структура

```
bot/                    # основной пакет
  __main__.py           # точка входа: Bot + Dispatcher + routers
  config.py             # Settings из .env (pydantic-settings)
  handlers/             # aiogram Router'ы
    start.py            # /start, /help
    photo.py            # прием фото -> AI анализ -> результат
    callbacks.py        # inline-кнопки (save/refine/cancel/menu/alt/detail)
    history.py          # /today, /history, /stats
    goal.py             # /goal (цели + параметры), /settings
    report.py           # /report - AI-анализ за период
    states.py           # FSM-состояния (RefineState, GoalEditState)
  services/
    vision/             # абстракция AI-провайдеров
      base.py           # ABC VisionProvider
      gemini.py         # Google Gemini
      openai_compat.py  # OpenAI/LM Studio/Ollama/Qwen
      factory.py        # фабрика + fallback-цепочка
    prompts.py          # рендеринг Jinja2-шаблонов
    nutrition.py        # парсинг JSON-ответа AI
    stats.py            # агрегация КБЖУ: день/неделя/период
  models/               # SQLAlchemy модели
    user.py             # User (профиль + цели + нормы КБЖУ)
    meal.py             # MealLog + MealItem
  keyboards/            # inline-клавиатуры
  middlewares/           # db session + auto user registration
  utils/                # форматеры (КБЖУ, прогресс-бар, светофор)
prompts/                # Jinja2-шаблоны промптов для AI
data/                   # SQLite БД + фото (на хосте, bind mount)
```

## Запуск

### Локально
```bash
cp .env.example .env    # заполнить BOT_TOKEN + GEMINI_API_KEY
uv sync
uv run alembic upgrade head
uv run python -m bot
```

### Docker
```bash
cp .env.example .env    # заполнить
docker compose up -d
```

Данные (БД + фото) хранятся в `./data/` на хосте.

## Развертка на сервере

1. Склонировать репозиторий
2. Скопировать `.env.example` в `.env`, заполнить:
   - `BOT_TOKEN` - токен Telegram бота (через @BotFather)
   - `GEMINI_API_KEY` - ключ Google Gemini API
   - Опционально: `OPENAI_API_KEY`, `OPENAI_BASE_URL` для фолбека
3. `docker compose up -d --build`
4. Миграции применяются автоматически (alembic upgrade head в entrypoint)
5. Данные в `./data/` - бекапить эту папку

## Ключевые решения

- **Промпты отделены от кода** - Jinja2-шаблоны в `prompts/`, можно менять без деплоя
- **Мульти-провайдер** - основной Gemini, фолбек на любой OpenAI-совместимый
- **Диапазоны КБЖУ** - AI возвращает min/max, в БД хранится среднее
- **FSM** - aiogram states для многошагового ввода (refine, goal edit)
- **Фото на диске** - `data/photos/{telegram_id}/` для будущего приложения
