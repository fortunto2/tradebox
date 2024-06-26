from fastapi import FastAPI, Request, HTTPException, Depends
import logging
from decimal import Decimal, ROUND_DOWN
from typing import List

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import SQLModel

from core.create_orders import calculate_orders, create_orders_in_db
from core.models.webhook import WebHook
from core.schema import WebhookPayload

app = FastAPI()
logging.basicConfig(level=logging.INFO)

from core.binance_futures import get_current_price, \
    create_order, check_open_orders, wait_order

# Global state to keep track of open positions
positions = {}

from core.db_async import async_session, async_engine, get_async_session


@app.on_event("startup")
async def on_startup():
    async with async_engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)


async def create_orders(payload: WebhookPayload, current_price: Decimal, webhook_id, session):

    orders = await create_orders_in_db(payload, current_price, webhook_id, session)

    for order in orders:
        print(order)
        order_id = await create_order(order)
        await wait_order(order["symbol"], order_id)
        break


@app.post("/webhook")
async def receive_webhook(body: WebhookPayload, session: AsyncSession = Depends(get_async_session)):
    logging.info(f"Received webhook JSON payload: {body.json()}")

    symbol = body.symbol

    # firstly check existing orders
    # open_orders = await check_open_orders(symbol)
    # if open_orders:
    #     logging.info(f"Open orders found for symbol: {symbol}. Ignoring new webhook.")
    #     return {"status": "ignored", "reason": "open orders found"}

    # save webhook to db
    webhook = WebHook(
        name=body.name,
        side=body.side.value,
        positionSide=body.positionSide.value,
        symbol=body.symbol,
        open=body.open.model_dump_json(),
        settings=body.settings.model_dump_json()
    )
    session.add(webhook)
    await session.commit()


    # current_price = get_current_price(symbol)
    current_price = Decimal(0.3634)
    logging.info(f"Current price for {symbol}: {current_price}")

    await create_orders(body, current_price, webhook.id, session)

    # Send the positions data as a string message to Telegram
    # tg = TelegramClient()
    # message = f"New position opened: {positions}"
    # tg.send_message(message=message)

    return {"status": "success"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, log_level="info", reload=True)
