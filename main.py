from fastapi import FastAPI, Request, HTTPException
import logging
from decimal import Decimal, ROUND_DOWN
from typing import List


from core.schema import WebhookPayload
from tg_client import TelegramClient
from config import settings

app = FastAPI()
logging.basicConfig(level=logging.INFO)

from core.binance_futures import client, get_symbol_price_and_quantity_by_precisions, ws_client, get_current_price, \
    create_order, monitor_order

# Global state to keep track of open positions
positions = {}


async def create_orders(payload: WebhookPayload, current_price: Decimal):
    orders = []
    settings = payload.settings
    mg_long = settings.mg_long
    grid_long = settings.grid_long

    initial_quantity = payload.open.amount
    total_spent = 0

    # firstly check existing orders
    await monitor_order(payload.symbol)

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
        await monitor_order(order["symbol"], order_id)
        break


@app.post("/webhook")
async def receive_webhook(body: WebhookPayload):
    logging.info(f"Received webhook JSON payload: {body.json()}")

    symbol = body.symbol

    if symbol in positions:
        logging.info(f"Position already open for symbol: {symbol}. Ignoring new webhook.")
        return {"status": "ignored", "reason": "position already open"}

    current_price = get_current_price(symbol)
    logging.info(f"Current price for {symbol}: {current_price}")

    await create_orders(body, current_price)

    positions[symbol] = {
        "side": body.side,
        "symbol": body.symbol,
        "amount": str(body.open.amount),
        "leverage": body.open.leverage,
    }

    # Send the positions data as a string message to Telegram
    # tg = TelegramClient()
    # message = f"New position opened: {positions}"
    # tg.send_message(message=message)

    return {"status": "success"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, log_level="info", reload=True)
