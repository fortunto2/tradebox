import json

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession

from config import get_settings

settings = get_settings()

from pydantic import BaseModel


def pydantic_serializer(value):
    if isinstance(value, BaseModel):
        # Pydantic модели имеют метод .json() для сериализации
        return value.model_dump_json()
    else:
        # Для всех других объектов используем стандартный json.dumps
        # с установкой default=str, чтобы не пропустить объекты несериализуемые json'ом по умолчанию
        return json.dumps(value, default=str)


if 'sqlite' in settings.DB_ASYNC_CONNECTION_STR:

    async_engine = create_async_engine(
        settings.DB_ASYNC_CONNECTION_STR,
        echo=settings.DEBUG,
        future=True,
        json_serializer=pydantic_serializer,
        connect_args={
            'timeout': 15,
        }

    )
else:
    async_engine = create_async_engine(
        settings.DB_ASYNC_CONNECTION_STR,
        echo=settings.DEBUG,
        future=True,
        json_serializer=pydantic_serializer,
        connect_args={
            'timeout': 15,
            'statement_cache_size': 0,
        },
        pool_recycle=3600,
        pool_size=100
    )


async_session = async_sessionmaker(bind=async_engine, class_=AsyncSession, expire_on_commit=False)


async def get_async_session():
    async with async_session() as session:
        yield session
