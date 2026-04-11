from datetime import date, datetime, timezone, timedelta

from pydantic_settings import BaseSettings

# Moscow timezone (UTC+3), used as default for all date/time operations.
# Override via TZ_OFFSET_HOURS env var if server moves to another timezone.
_TZ_OFFSET_HOURS = 3
_TZ = timezone(timedelta(hours=_TZ_OFFSET_HOURS))


def now_local() -> datetime:
    """Current datetime in configured timezone (naive, for DB storage)."""
    return datetime.now(_TZ).replace(tzinfo=None)


def today_local() -> date:
    """Current date in configured timezone."""
    return datetime.now(_TZ).date()


class Settings(BaseSettings):
    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    # Telegram
    bot_token: str = ""

    # AI Vision (primary + fallback)
    vision_provider: str = "openai_compat"
    vision_fallback: str = "gemini"

    # Google Gemini
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"

    # OpenAI-compatible (primary - for photo analysis via OpenRouter)
    openai_api_key: str = ""
    openai_base_url: str = "https://openrouter.ai/api/v1"
    openai_model: str = "openai/gpt-4.1-mini"

    # Local model (LM Studio / Ollama) - for classifier + text questions
    local_base_url: str = ""
    local_model: str = "google/gemma-4-26b-a4b"
    local_api_key: str = "lm-studio"
    local_reasoning_effort: str = "none"

    # Text-only fallback model (OpenRouter, if local unavailable)
    text_model: str = "openai/gpt-4.1-nano"

    # Database
    database_url: str = "postgresql+asyncpg://snap:snap@localhost:5432/snapcalories"

    # Embedding (для векторного поиска)
    embedding_model: str = "gemini-embedding-001"
    embedding_dimensions: int = 768


settings = Settings()
