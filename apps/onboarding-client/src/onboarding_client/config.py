from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_name: str = "onboarding-client"
    app_env: str = "dev"
    database_url: str = "sqlite:///./data/onboarding_client.db"
    public_base_url: str = "http://localhost:8000"

    dex_jwks_url: str = ""
    dex_issuers: str = ""
    dex_audience: str = ""
    dex_email_allowlist: str = ""
    dex_required_group: str = ""

    resend_api_key: str = ""
    resend_from_email: str = ""
    resend_reply_to: str = ""


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
