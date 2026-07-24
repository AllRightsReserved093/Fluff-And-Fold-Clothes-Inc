# Load application settings from environment variables.

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


# Define environment-backed application settings.
class Settings(BaseSettings):
    app_name: str = "Fluff and Fold Clothes Inc API"
    app_version: str = "0.1.0"
    api_v1_prefix: str = "/api/v1"
    debug: bool = False
    database_url: str = "sqlite:///./laundry.db"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="FFC_",
        extra="ignore",
    )


# Reuse one validated settings instance per process.
@lru_cache
def get_settings() -> Settings:
    return Settings()
