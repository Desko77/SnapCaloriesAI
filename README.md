# SnapCaloriesAI

Telegram-бот для расчета калорий и макронутриентов (КБЖУ) по фотографиям еды с помощью AI.

## Возможности

- Анализ фото еды через AI Vision (Google Gemini / OpenAI-совместимые модели)
- Детализация по продуктам с диапазонами КБЖУ
- Система "светофор" - оценка приема пищи (зеленый/желтый/красный)
- Советы по оптимизации блюда
- Уточнение результата ("там творог, а не сыр") с пересчетом
- История приемов пищи за день/неделю
- AI-отчет за период (неделя/месяц) с анализом паттернов и трендов
- Цели: похудение, набор мышечной массы, рекомпозиция и др.
- Хранение фото и истории для будущего веб/мобильного приложения

## Стек

- **Python 3.12+** / aiogram 3.x
- **AI Vision**: Google Gemini (основной), OpenAI-совместимый API (фолбек: LM Studio, Ollama, Qwen)
- **БД**: SQLAlchemy 2.0 + SQLite (async)
- **Промпты**: Jinja2-шаблоны (отделены от кода)
- **Docker**: один контейнер, данные на хосте

**[Полная инструкция по настройке](docs/setup-guide.md)** - от создания бота до запуска на сервере.

## Быстрый старт

```bash
# клонировать
git clone https://github.com/Desko77/SnapCaloriesAI.git
cd SnapCaloriesAI

# настроить
cp .env.example .env
# заполнить BOT_TOKEN и GEMINI_API_KEY в .env

# запуск через Docker
docker compose up -d --build

# или локально
uv sync
uv run alembic upgrade head
uv run python -m bot
```

## Переменные окружения

| Переменная | Описание | Обязательная |
|-----------|----------|:---:|
| `BOT_TOKEN` | Токен Telegram бота (@BotFather) | да |
| `GEMINI_API_KEY` | Google Gemini API key | да* |
| `GEMINI_MODEL` | Модель Gemini (default: gemini-2.5-flash) | нет |
| `OPENAI_API_KEY` | OpenAI / совместимый API key | нет |
| `OPENAI_BASE_URL` | URL API (LM Studio, Ollama) | нет |
| `OPENAI_MODEL` | Модель (default: gpt-4o) | нет |
| `VISION_PROVIDER` | Основной провайдер: gemini / openai_compat | нет |
| `VISION_FALLBACK` | Фолбек провайдер | нет |
| `DATABASE_URL` | URL БД (default: sqlite) | нет |

*Обязателен хотя бы один AI-провайдер (Gemini или OpenAI-совместимый).

## Команды бота

| Команда | Описание |
|---------|----------|
| `/start` | Начать работу |
| `/today` | Итого за сегодня |
| `/history` | История за неделю |
| `/stats` | Статистика |
| `/report` | AI-анализ за период |
| `/goal` | Цели и параметры |
| `/settings` | Настройки (режим ответа) |
| `/help` | Справка |

## Архитектура

```
Telegram -> aiogram handlers -> AI Vision provider -> Jinja2 prompt -> Gemini/OpenAI
                                                                          |
                                                                     JSON response
                                                                          |
                                                              nutrition parser -> DB
```

AI-провайдеры подключаются через абстракцию `VisionProvider` с автоматическим фолбеком.
Промпты - Jinja2-шаблоны в `prompts/`, можно менять без изменения кода.

## Лицензия

MIT
