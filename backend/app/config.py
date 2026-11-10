from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=Path(__file__).resolve().parent.parent / ".env", extra="ignore")
    database_url: str = "sqlite:///./dev.db"
    trading_mode: str = "PAPER"
    admin_token: str = ""
    secret_key: str = "dev-only-change-me"
    collectors_enabled: bool = True
    trading_service_enabled: bool = True


settings = Settings()
