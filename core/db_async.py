import json

from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession

from config import get_settings

settings = get_settings()

from pydantic import BaseModel


def pydantic_serializer(value):
    if isinstance(value, BaseModel):
        # Pydantic модели имеют метод .json() для сериализации
        return value.json()
    else:
        # Для всех других объектов используем стандартный json.dumps
        # с установкой default=str, чтобы не пропустить объекты несериализуемые json'ом по умолчанию
        return json.dumps(value, default=str)


async_engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    future=True,
    json_serializer=pydantic_serializer
)

async_session = sessionmaker(bind=async_engine, class_=AsyncSession, expire_on_commit=False)


async def get_async_session():
    async with async_session() as session:
        yield session
