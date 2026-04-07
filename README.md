# SnapCaloriesAI

Telegram-бот для расчета калорий и макронутриентов (КБЖУ) по фотографиям еды с помощью AI.

## Возможности

- Анализ фото еды через AI Vision (Google Gemini / OpenAI-совместимые модели)
- Детализация по продуктам с диапазонами КБЖУ
- Система "светофор" - оценка приема пищи (зеленый/желтый/красный)
- Советы по оптимизации блюда и рекомендации замен
- Уточнение результата ("там творог, а не сыр") с пересчетом
- Группировка приемов пищи: несколько фото за раз, добавление к последнему приему
- AI-анализ дня: плюсы, проблемы, скрытые враги, оценка
- История приемов пищи за день/неделю/месяц с графиками
- AI-отчет за период с анализом паттернов и трендов
- Планирование меню на день/неделю/месяц со списком покупок
- Сравнение факта с планом (+-10% = совпал)
- Цели: похудение, набор мышечной массы, рекомпозиция и др.
- Текстовые вопросы по питанию (без фото)
- Хранение фото и истории для будущего веб/мобильного приложения

## Стек

- **Python 3.12+** / aiogram 3.x
- **AI Vision**: Google Gemini (основной), OpenAI-совместимый API (фолбек: OpenRouter, LM Studio, Ollama)
- **БД**: SQLAlchemy 2.0 + SQLite (async), Alembic миграции
- **Промпты**: Jinja2-шаблоны (отделены от кода)
- **Docker**: один контейнер, данные на хосте / [Docker Hub](https://hub.docker.com/r/desko77/snapcaloriesai)

**[Полная инструкция по настройке](docs/setup-guide.md)** - от создания бота до запуска на сервере.

## Быстрый старт

### Docker Hub (самый быстрый)

```bash
mkdir snapcaloriesai && cd snapcaloriesai
# создать .env с BOT_TOKEN и GEMINI_API_KEY
docker run -d --name snapcaloriesai \
  -v ./data:/app/data --env-file .env \
  --restart unless-stopped \
  desko77/snapcaloriesai:latest
```

### Docker Compose

```bash
git clone https://github.com/Desko77/SnapCaloriesAI.git
cd SnapCaloriesAI
cp .env.example .env
# заполнить BOT_TOKEN и GEMINI_API_KEY в .env
docker compose up -d --build
```

### Локально

```bash
git clone https://github.com/Desko77/SnapCaloriesAI.git
cd SnapCaloriesAI
cp .env.example .env
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
| `/today` | Итого за сегодня + AI-анализ дня |
| `/history` | История за неделю с графиком |
| `/stats` | Статистика за период |
| `/report` | AI-отчет за период с трендами |
| `/menu` | Планирование меню (день/неделя/месяц) |
| `/goal`, `/profile` | Цели и параметры |
| `/settings` | Настройки |
| `/help` | Справка |

## Архитектура

```
Telegram -> aiogram handlers -> AI Vision provider -> Jinja2 prompt -> Gemini/OpenAI
                                                                          |
                                                                     JSON response
                                                                          |
                                                              nutrition parser -> DB
```

- AI-провайдеры подключаются через абстракцию `VisionProvider` с автоматическим фолбеком
- Промпты - Jinja2-шаблоны в `prompts/`, можно менять без изменения кода
- Данные (БД + фото) хранятся на хосте через bind mount `./data/`

## Лицензия

MIT
