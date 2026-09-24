from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore")

    supabase_url: str = ""
    supabase_service_role_key: str = ""
    database_url: str = ""
    telegram_bot_token: str = ""
    # polling: local dev · webhook: deployed (Telegram pushes to PUBLIC_URL/telegram/webhook) · off: no bot
    bot_mode: str = "polling"
    public_url: str = ""  # e.g. https://kaintabe-api.up.railway.app
    webhook_secret: str = ""  # checked against Telegram's X-Telegram-Bot-Api-Secret-Token header
    anthropic_api_key: str = ""
    ai_model: str = "claude-sonnet-5"
    # comma-separated, e.g. "http://localhost:5173,https://kaintabe.vercel.app"
    frontend_origin: str = "http://localhost:5173"

    # The public web app (opened as a Telegram Mini App). Defaults to the first https FRONTEND_ORIGIN.
    web_url: str = ""

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip().rstrip("/") for o in self.frontend_origin.split(",") if o.strip()]

    @property
    def map_url(self) -> str | None:
        """HTTPS URL for 'Open map' buttons, or None (Telegram only opens https web apps)."""
        candidates = [self.web_url.rstrip("/")] + self.cors_origins
        return next((u for u in candidates if u.startswith("https://")), None)


settings = Settings()
settings.supabase_url = settings.supabase_url.rstrip("/")
settings.public_url = settings.public_url.rstrip("/")
if settings.public_url and "://" not in settings.public_url:
    settings.public_url = f"https://{settings.public_url}"  # Telegram webhooks must be HTTPS
