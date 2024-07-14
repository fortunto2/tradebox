from fastapi import FastAPI, HTTPException, Depends
import logging

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import SQLModel

from core.binance_futures import check_position_side_dual, check_position
from core.schemas.position import LongPosition
from trade.orders.orders_processing import open_long_position
from core.models.webhook import WebHook
from core.schemas.webhook import WebhookPayload
from core.tg_client import TelegramClient

app = FastAPI()
logging.basicConfig(level=logging.INFO)

from core.db_async import async_engine, get_async_session


import logging

from starlette.responses import JSONResponse

from fastapi import FastAPI, Request, HTTPException
from fastapi.exceptions import RequestValidationError


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    logging.error(f"Validation error: {exc}")
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors(), "body": exc.body},
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    logging.error(f"HTTP error: {exc}")
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    logging.error(f"An unexpected error occurred: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "An unexpected error occurred."},
    )


@app.on_event("startup")
async def on_startup():
    async with async_engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    #     check dual mode
    dual_mode = await check_position_side_dual()
    if not dual_mode:
        raise HTTPException(status_code=403, detail="Failed to set dual mode, check Binance settings!")


@app.post("/webhook")
async def receive_webhook(body: WebhookPayload, session: AsyncSession = Depends(get_async_session)):
    logging.info(f"Received webhook JSON payload: {body.json()}")

    symbol = body.symbol
    # if last characher in symbol P, remove it
    if symbol[-2:] == '.P':
        symbol = symbol[:-2]

    body.symbol = symbol

    position_long, _ = await check_position(symbol=symbol)
    position_long: LongPosition

    if float(position_long.entryPrice) > 0:
        print(position_long)
        print(f"Position found for symbol: {symbol}. Ignoring new webhook.")
        return {"status": "ignored", "reason": f"position found for {symbol}"}

    # save webhook to db
    webhook = WebHook(
        name=body.name,
        side=body.side.value,
        positionSide=body.positionSide.value,
        symbol=symbol,
        open=body.open,
        settings=body.settings
    )
    session.add(webhook)
    await session.commit()

    # Send the positions data as a string message to Telegram
    tg = TelegramClient()
    message = f"New webhook: {webhook.model_dump_json()}"
    tg.send_message(message=message)

    # current_price = get_current_price(symbol)
    # logging.info(f"Current price for {symbol}: {current_price}")

    await open_long_position(body, webhook.id, session)
    # tg.send_message(message=first_order.model_dump_json())

    return {"status": "success"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, log_level="info", reload=True)
