from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore")

    supabase_url: str = ""
    supabase_service_role_key: str = ""
    database_url: str = ""
    telegram_bot_token: str = ""
    bot_mode: str = "polling"
    anthropic_api_key: str = ""
    frontend_origin: str = "http://localhost:5173"


settings = Settings()
