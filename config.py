import os

from functools import lru_cache
from pydantic import AnyUrl, validator
from typing import Optional, Dict, Any

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    BASE_DIR: str = os.path.dirname(os.path.realpath(__file__))
    ENVIRONMENT: str = "dev"

    BINANCE_API_KEY: str
    BINANCE_API_SECRET: str

    class Config:
        case_sensitive = True
        env_file = ".env"


@lru_cache()
def get_settings():
    return Settings()


settings = get_settings()
