from fastapi import FastAPI, Request, HTTPException, Depends
import logging
from decimal import Decimal, ROUND_DOWN
from typing import List

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import SQLModel

from core.create_orders import calculate_prices, create_orders_in_db
from core.models.orders import Order
from core.schema import WebhookPayload
from tg_client import TelegramClient
from config import settings

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


async def create_orders(payload: WebhookPayload, current_price: Decimal):
    orders = []
    settings = payload.settings
    mg_long = settings.mg_long
    grid_long = settings.grid_long

    initial_quantity = payload.open.amount
    total_spent = 0

    for i in range(settings.order_quan):
        if i < len(mg_long) and i < len(grid_long):
            price = current_price * Decimal(1 + grid_long[i] / 100)
            quantity = initial_quantity * Decimal(mg_long[i] / 100)
            cost = price * quantity

            if total_spent + cost > settings.deposit:
                break

            total_spent += cost
            orders.append({
                "symbol": payload.symbol,
                "side": payload.side,
                "price": str(price),
                "quantity": str(quantity),
                "leverage": payload.open.leverage
            })

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
    open_orders = await check_open_orders(symbol)
    if open_orders:
        logging.info(f"Open orders found for symbol: {symbol}. Ignoring new webhook.")
        return {"status": "ignored", "reason": "open orders found"}

    current_price = get_current_price(symbol)
    logging.info(f"Current price for {symbol}: {current_price}")

    await create_orders_in_db(body, current_price, session)

    # Send the positions data as a string message to Telegram
    # tg = TelegramClient()
    # message = f"New position opened: {positions}"
    # tg.send_message(message=message)

    return {"status": "success"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, log_level="info", reload=True)
