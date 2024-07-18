import sentry_sdk
import logging

from fastapi import FastAPI

from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import sessionmaker

from sentry_sdk.integrations.asgi import SentryAsgiMiddleware
from typing import Optional

from config import settings

from core.db import (
    close_database_connection,
    close_database_ping_connection,
    setup_database_connection,
    setup_database_ping_connection,
)


class FastAPIApp(FastAPI):
    async_session: sessionmaker
    # DB engines
    db_engine: AsyncEngine
    ping_db_engine: AsyncEngine

    docs_url: Optional[str] = None
    redoc_url: Optional[str] = None
    openapi_url: Optional[str] = None
    root_path: str = ""

    def __init__(self, *args, **kwargs):  # type: ignore
        self.init_swagger()

        super().__init__(
            title=f"{settings.APP_NAME} API",
            version=f"0.1.0",
            docs_url=self.docs_url,
            redoc_url=self.redoc_url,
            openapi_url=self.openapi_url,
            root_path=self.root_path,
            *args,
            **kwargs,
        )

    def init_base(self) -> None:
        exceptions_init.handle_exceptions(self)
        self.setup_logging()

    def init_web(self) -> None:
        self.init_base()
        self.init_api_routers()

        @self.on_event("startup")
        async def on_startup() -> None:
            FastAPICache.init(InMemoryBackend(), prefix="fastapi-cache")
            set_logger_config(
                logger_name=settings.BASE_LOGGER_NAME,
                level_logger=logging.INFO if settings.DEBUG else logging.WARNING,
            )

        @self.on_event("startup")
        async def on_startup_app_middlewares() -> None:
            from app.middlewares import init_middlewares

            init_middlewares(self)

        @self.on_event("startup")
        async def on_startup_app_base() -> None:
            await setup_database_connection(self)
            await setup_database_ping_connection(self)

        @self.on_event("shutdown")
        async def on_shutdown_app_base() -> None:
            await close_database_connection(self)
            await close_database_ping_connection(self)

    def init_api_routers(self) -> None:
        from router import app_router

        self.include_router(app_router)

        logger.debug(f"init_api_routers")

    def init_swagger(self) -> None:
        if settings.SWAGGER:
            logger.debug(f"init_swagger")

            self.docs_url = "/api/v1/swagger"
            self.redoc_url = "/api/v1/redoc"
            self.openapi_url = "/api/v1/openapi.json"

    def setup_logging(self) -> None:
        if settings.DEBUG or not settings.SENTRY_DSN:
            return

        sentry_sdk.init(
            dsn=settings.SENTRY_DSN,
            traces_sample_rate=1.0,
        )
        sentry_sdk.set_level("debug")

        SentryAsgiMiddleware(self)
