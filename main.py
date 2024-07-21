from fastapi import FastAPI, Depends
import logging

import sentry_sdk
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from config import settings
from core.clients.db_async import get_async_session, async_engine
from core.clients.db_sync import SessionLocal, sync_engine
from core.models.binance_symbol import BinanceSymbol
# from core.clients.db_sync import sync_engine
from flows.open_long_potition import open_long_position

sentry_sdk.init(
    dsn="https://c167125710805940a14cc72b74bf2617@o103263.ingest.us.sentry.io/4507614078238720",
    # Set traces_sample_rate to 1.0 to capture 100%
    # of transactions for performance monitoring.
    traces_sample_rate=1.0,
    # Set profiles_sample_rate to 1.0 to profile 100%
    # of sampled transactions.
    # We recommend adjusting this value in production.
    profiles_sample_rate=1.0,
)

from flows.tasks.binance_futures import check_position_side_dual, check_position
from core.models.orders import Order
from core.schemas.position import LongPosition
from core.models.webhook import WebHook
from core.schemas.webhook import WebhookPayload
from core.clients.tg_client import TelegramClient

app = FastAPI()
logging.basicConfig(level=logging.INFO)


import logging

from starlette.responses import JSONResponse

from fastapi import Request, HTTPException
from fastapi.exceptions import RequestValidationError

from sqladmin import Admin, ModelView

admin = Admin(app, engine=async_engine, base_url="/rust_admin")

class WebhooksAdmin(ModelView, model=WebHook):
    can_create = True
    can_edit = False
    can_delete = False
    column_list = [WebHook.id, WebHook.symbol]
    # column_searchable_list = [WebHook.symbol]
    # column_sortable_list = [WebHook.id]
    # column_formatters = {WebHook.symbol: lambda m, a: m.symbol[:10]}
    # column_default_sort = [(WebHook.id, True), (WebHook.symbol, False)]


admin.add_view(WebhooksAdmin)

class BinanceSymbolAdmin(ModelView, model=BinanceSymbol):
    can_create = False
    can_edit = False
    can_delete = False
    column_list = [BinanceSymbol.symbol, BinanceSymbol.quantity_precision, BinanceSymbol.price_precision]

admin.add_view(BinanceSymbolAdmin)

class OrdersAdmin(ModelView, model=Order):
    can_create = False
    can_edit = False
    can_delete = False
    column_list = [Order.id, Order.binance_id, Order.symbol, Order.webhook_id, Order.position_side, Order.side, Order.status, Order.type, Order.created_at]
    column_searchable_list = [Order.symbol, Order.webhook_id, Order.binance_id]
    column_sortable_list = [Order.id, Order.symbol, Order.webhook_id, Order.position_side, Order.side, Order.status,
                            Order.type, Order.created_at, Order.binance_id]
    column_formatters = {Order.symbol: lambda m, a: m.symbol[:10]}
    column_default_sort = [(Order.id, True), (Order.symbol, False)]
    column_filters = [Order.symbol, Order.webhook_id, Order.position_side, Order.side, Order.status]


# admin.add_view(WebhooksAdmin)
admin.add_view(OrdersAdmin)


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
    # if sqllite in settings
    if settings.DB_CONNECTION_STR.startswith("sqlite"):
        SQLModel.metadata.create_all(sync_engine)

    #     check dual mode
    dual_mode = check_position_side_dual()
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

    # todo: check if position already exists in db
    # если слишком быстро пришло много вебхуков на один символ, все отработают

    position_long, _ = check_position(symbol=symbol)
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

    # async to thread run
    await open_long_position(body, webhook.id)
    await session.close()

    # tg.send_message(message=first_order.model_dump_json())

    return {"status": "success"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8009, log_level="info", reload=True)
