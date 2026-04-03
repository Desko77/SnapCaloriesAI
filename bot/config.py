from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    # Telegram
    bot_token: str = ""

    # AI Vision
    vision_provider: str = "gemini"
    vision_fallback: str = "openai_compat"

    # Google Gemini
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"

    # OpenAI-compatible
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o"

    # Database
    database_url: str = "sqlite+aiosqlite:///data/snapcalories.db"


settings = Settings()
