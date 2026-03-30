from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_name: str = "telegram-service"
    app_env: str = "dev"
    app_base_path: str = ""

    database_url: str = "sqlite:///./data/telegram_gateway.db"

    admin_session_secret: str = "change-me"
    admin_cookie_name: str = "tg_admin_session"
    admin_username: str = "admin"
    admin_password: str = "admin123"

    dex_jwks_url: str = ""
    dex_issuers: str = ""
    dex_audience: str = ""
    dex_email_allowlist: str = ""
    dex_required_group: str = ""

    secret_backend: str = "env"
    gateway_secret_master_key: str = ""
    telegram_api_base: str = "https://api.telegram.org"

    webhook_shared_secret: str = ""


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
