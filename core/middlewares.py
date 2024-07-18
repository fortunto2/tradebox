import time

from typing import Any, Callable

from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from config import settings

from app.db import get_db_engine_and_session


def init_middlewares(app) -> None:
    @app.middleware("http")
    async def time_header_middleware(request: Request, call_next: Callable) -> Any:
        return await add_process_time_header(request, call_next)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS.split(","),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.add_middleware(RequestDBConnMiddleware)


class RequestDBConnMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Any:
        request.state.db, request.state.async_session = await get_db_engine_and_session()
        return await call_next(request)


async def add_process_time_header(request: Request, call_next: Callable) -> Any:
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = str(process_time)
    return response
