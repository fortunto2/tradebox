import os

from functools import lru_cache
from pydantic import AnyUrl, validator, PostgresDsn, field_validator
from typing import Optional, Dict, Any, List, Union

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DEBUG: bool = False
    TIMEZONE: str = "Europe/Moscow"

    BASE_DIR: str = os.path.dirname(os.path.realpath(__file__))
    ENVIRONMENT: str = "dev"

    BINANCE_API_KEY: str
    BINANCE_API_SECRET: str

    DB_CONNECTION_STR: str = "sqlite+aiosqlite:///./tradebox.db"
    DB_ASYNC_CONNECTION_STR: str = "sqlite+aiosqlite:///./tradebox.db"

    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = ""
    POSTGRES_DB: str = "tradebox"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: str = "5432"

    PREFECT_API_URL: str = "http://127.0.0.1:4200/api"

    SYMBOLS: Union[str, List[str]] = ["ADAUSDT"]

    @field_validator('SYMBOLS', mode='before')
    def split_symbols(cls, v):
        return v.split(',') if isinstance(v, str) else v

    class Config:
        case_sensitive = True
        env_file = ".env"


@lru_cache()
def get_settings():
    return Settings()


settings = get_settings()
