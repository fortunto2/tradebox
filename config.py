import os

from functools import lru_cache
from pydantic import AnyUrl, validator, PostgresDsn, field_validator
from typing import Optional, Dict, Any

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DEBUG: bool = False

    BASE_DIR: str = os.path.dirname(os.path.realpath(__file__))
    ENVIRONMENT: str = "dev"

    BINANCE_API_KEY: str
    BINANCE_API_SECRET: str

    DATABASE_URL: str = "sqlite+aiosqlite:///./test.db"

    DB_ASYNC_CONNECTION_STR: str ="postgresql+asyncpg://postgres:rust_admin@45.32.253.11:5432/tradebox"

    class Config:
        case_sensitive = True
        env_file = ".env"


@lru_cache()
def get_settings():
    return Settings()


settings = get_settings()
