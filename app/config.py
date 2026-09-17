from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    gemini_api_key: str
    database_url: str = "postgresql+asyncpg://appuser:apppassword@db:5432/appdb"
    app_timezone: str = "Asia/Kolkata"

    ocr_confidence_threshold: float = 0.5
    entity_confidence_threshold: float = 0.6

    gemini_model: str = "gemini-2.5-pro"


@lru_cache
def get_settings() -> Settings:
    return Settings()
