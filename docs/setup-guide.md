# Инструкция по настройке SnapCaloriesAI

Пошаговая инструкция от нуля до работающего бота.

---

## 1. Создание Telegram-бота

1. Откройте Telegram, найдите **@BotFather**
2. Отправьте `/newbot`
3. Введите имя бота (отображаемое): `SnapCaloriesAI`
4. Введите username бота (уникальный, с суффиксом _bot): `SnapCaloriesAI_bot`
5. BotFather пришлет **токен** вида `7123456789:AAFxxxxxxxxxxxxxxxxxxxxxxx` - сохраните его

### Дополнительные настройки бота (опционально)

В @BotFather:
- `/setdescription` - описание бота (видно при первом открытии): "AI-нутрициолог. Отправь фото еды - рассчитаю КБЖУ"
- `/setabouttext` - текст "О боте": "Персональный AI-помощник для анализа питания по фото"
- `/setuserpic` - аватарка бота

---

## 2. Получение API-ключа Google Gemini

1. Перейдите на https://aistudio.google.com/apikey
2. Нажмите **Create API Key**
3. Выберите проект (или создайте новый)
4. Скопируйте ключ вида `AIzaSy...`

Бесплатный тир Gemini: 15 запросов/минуту, 1500 запросов/день - достаточно для личного использования.

---

## 3. (Опционально) OpenAI-совместимый провайдер

Если хотите фолбек или альтернативный провайдер:

### OpenAI
1. https://platform.openai.com/api-keys -> Create new secret key
2. Скопируйте ключ `sk-...`

### LM Studio (локальная модель)
1. Установите LM Studio: https://lmstudio.ai
2. Скачайте модель с поддержкой vision (например Llava, Qwen-VL)
3. Запустите сервер: вкладка Local Server -> Start Server
4. URL по умолчанию: `http://localhost:1234/v1`

### Ollama (локальная модель)
1. Установите Ollama: https://ollama.ai
2. Скачайте модель: `ollama pull llava`
3. URL: `http://localhost:11434/v1`

---

## 4. Настройка проекта

### Вариант A: Docker (рекомендуется)

```bash
# Клонировать репозиторий
git clone https://github.com/Desko77/SnapCaloriesAI.git
cd SnapCaloriesAI

# Создать файл настроек
cp .env.example .env
```

Отредактируйте `.env`:
```env
# === ОБЯЗАТЕЛЬНЫЕ ===
BOT_TOKEN=7123456789:AAFxxxxxxxxxxxxxxxxxxxxxxx
GEMINI_API_KEY=AIzaSyxxxxxxxxxxxxxxxxxxxxxxxxx

# === ОПЦИОНАЛЬНЫЕ ===
# Модель Gemini (по умолчанию gemini-2.5-flash)
# GEMINI_MODEL=gemini-2.5-flash

# Фолбек-провайдер (OpenAI, LM Studio, Ollama)
# OPENAI_API_KEY=sk-xxx
# OPENAI_BASE_URL=https://api.openai.com/v1
# OPENAI_MODEL=gpt-4o

# Основной провайдер: gemini или openai_compat
# VISION_PROVIDER=gemini
# VISION_FALLBACK=openai_compat

# База данных (по умолчанию SQLite в ./data/)
# DATABASE_URL=sqlite+aiosqlite:///data/snapcalories.db
```

Запустите:
```bash
docker compose up -d --build
```

Проверьте что работает:
```bash
docker compose logs -f
```

Должно быть: `Bot starting...`

### Вариант B: Локально без Docker

```bash
# Клонировать
git clone https://github.com/Desko77/SnapCaloriesAI.git
cd SnapCaloriesAI

# Установить uv (если нет)
# Windows:
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
# Linux/macOS:
# curl -LsSf https://astral.sh/uv/install.sh | sh

# Установить зависимости
uv sync

# Настроить .env
cp .env.example .env
# Заполнить BOT_TOKEN и GEMINI_API_KEY

# Применить миграции БД
uv run alembic upgrade head

# Запустить бота
uv run python -m bot
```

### Вариант C: Docker Hub (самый быстрый)

```bash
# Создать папку для данных
mkdir -p snapcaloriesai/data
cd snapcaloriesai

# Создать .env
cat > .env << 'EOF'
BOT_TOKEN=ваш_токен
GEMINI_API_KEY=ваш_ключ
EOF

# Запустить
docker run -d \
  --name snapcaloriesai \
  -v ./data:/app/data \
  --env-file .env \
  --restart unless-stopped \
  desko77/snapcaloriesai:latest
```

---

## 5. Проверка работы

1. Откройте бота в Telegram (по username из шага 1)
2. Нажмите **Start** или отправьте `/start`
3. Должно появиться приветственное сообщение
4. Отправьте фото еды - бот должен проанализировать

Если бот не отвечает:
```bash
# Docker:
docker compose logs --tail 50

# Локально: посмотрите вывод в терминале
```

Типичные ошибки:
- `BOT_TOKEN is not set` - не заполнен токен в .env
- `Gemini API key not configured` - не заполнен GEMINI_API_KEY
- `404 NOT_FOUND model` - устаревшая модель, обновите GEMINI_MODEL

---

## 6. Настройка бота после запуска

### Установить цели
В Telegram: `/goal` -> выберите тип цели, введите вес, рост, целевой вес, нормы КБЖУ.

### Режим ответа
`/settings` -> переключить между компактным и развернутым.

### Посмотреть команды
Нажмите `/` в поле ввода - появится меню команд на русском.

---

## 7. Обновление

### Docker Compose
```bash
cd SnapCaloriesAI
git pull
docker compose up -d --build
```

### Docker Hub
```bash
docker pull desko77/snapcaloriesai:latest
docker stop snapcaloriesai
docker rm snapcaloriesai
docker run -d \
  --name snapcaloriesai \
  -v ./data:/app/data \
  --env-file .env \
  --restart unless-stopped \
  desko77/snapcaloriesai:latest
```

Данные (БД + фото) хранятся в `./data/` на хосте и не теряются при обновлении.

---

## 8. Бекапы

Все данные - в папке `data/`:
- `data/snapcalories.db` - база данных (пользователи, приемы пищи, КБЖУ)
- `data/photos/` - фотографии еды по пользователям

Для бекапа достаточно скопировать папку `data/`.

---

## Структура .env (полная)

| Переменная | По умолчанию | Описание |
|-----------|-------------|----------|
| `BOT_TOKEN` | - | Токен Telegram бота (обязательно) |
| `GEMINI_API_KEY` | - | Google Gemini API ключ |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Модель Gemini |
| `OPENAI_API_KEY` | - | OpenAI / совместимый ключ |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | URL API |
| `OPENAI_MODEL` | `gpt-4o` | Модель OpenAI |
| `VISION_PROVIDER` | `gemini` | Основной провайдер |
| `VISION_FALLBACK` | `openai_compat` | Резервный провайдер |
| `DATABASE_URL` | `sqlite+aiosqlite:///data/snapcalories.db` | URL базы данных |
