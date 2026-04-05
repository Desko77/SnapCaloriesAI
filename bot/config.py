from pydantic_settings import BaseSettings


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

    # OpenAI-compatible (primary - for photo analysis)
    openai_api_key: str = ""
    openai_base_url: str = "https://openrouter.ai/api/v1"
    openai_model: str = "openai/gpt-4.1-mini"

    # Cheap model for text-only questions (no vision needed)
    text_model: str = "openai/gpt-4.1-nano"

    # Database
    database_url: str = "sqlite+aiosqlite:///data/snapcalories.db"


settings = Settings()
