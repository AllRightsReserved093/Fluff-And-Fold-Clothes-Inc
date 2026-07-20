# Load application settings from environment variables.
# 从环境变量加载应用配置。

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Fluff and Fold Clothes Inc API"
    app_version: str = "0.1.0"
    api_v1_prefix: str = "/api/v1"
    debug: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="FFC_",
        extra="ignore",
    )


# Reuse one validated settings instance per process.
# 每个进程复用一个经过验证的配置实例。
@lru_cache
def get_settings() -> Settings:
    return Settings()
