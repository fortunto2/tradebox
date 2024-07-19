from typing import Any, Tuple

from aiopg.sa import create_engine
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from config import settings


async def setup_database_connection(app: Any) -> None:
    app.db_engine = create_async_engine(
        url=f"postgresql+asyncpg://{settings.DB_USER}:{settings.DB_PASSWORD}@{settings.DB_HOST}:{settings.DB_PORT}/{settings.DB_NAME}",
        pool_recycle=settings.DB_RECYCLE,
        pool_size=settings.DB_MAX_CONNECTIONS,
        echo=settings.DB_ECHO,
    )
    app.async_session = sessionmaker(app.db_engine, expire_on_commit=False, class_=AsyncSession, )


async def setup_database_ping_connection(app: Any) -> None:
    # This separated connection is used only for ping
    # Because on high load there is no db connections is available in aiopg.Pool.
    # This leads to health check fail and restarting Kube Pods. Rolling blackout
    app.ping_db_engine = await create_engine(
        user=settings.DB_USER,
        password=settings.DB_PASSWORD,
        host=settings.DB_HOST,
        port=settings.DB_PORT,
        database=settings.DB_NAME,
        maxsize=1,
        echo=settings.DB_ECHO,
    )


async def close_database_connection(app: Any) -> None:
    await app.db_engine.dispose()


async def close_database_ping_connection(app: Any) -> None:
    app.ping_db_engine.close()
    await app.ping_db_engine.wait_closed()


async def get_db_engine_and_session() -> Tuple[AsyncEngine, sessionmaker]:
    from main import app

    return app.db_engine, app.async_session


async def get_ping_db_engine() -> AsyncEngine:
    from main import app

    return app.ping_db_engine
