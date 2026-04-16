import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite:///./authz-manager.db"
    DEX_JWKS_URL: str = os.getenv("DEX_JWKS_URL", "http://dex.dex.svc.cluster.local:5556/keys")
    AUTH_ENABLED: bool = True
    
    # Bootstrap admin
    BOOTSTRAP_ADMIN_EMAIL: str | None = os.getenv("BOOTSTRAP_ADMIN_EMAIL")
    
    model_config = {
        "env_file": ".env"
    }

settings = Settings()
