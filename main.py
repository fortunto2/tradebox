from fastapi import FastAPI, Request, HTTPException
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ValidationError
import logging
from decimal import Decimal, ROUND_DOWN
from typing import List

import asyncio

from starlette.responses import JSONResponse

from core.schema import WebhookPayload
from tg_client import TelegramClient
from config import settings

app = FastAPI()
logging.basicConfig(level=logging.INFO)

from core.binance_futures import client

# Global state to keep track of open positions
positions = {}


def get_current_price(symbol: str) -> Decimal:
    try:
        ticker = client.ticker_price(symbol)
        return Decimal(ticker.get('price'))
    except Exception as e:
        logging.error(f"Failed to get current price: {e}")
        raise HTTPException(status_code=500, detail="Failed to get current price")


async def create_order_spot(order):
    """
    features: https://binance-docs.github.io/apidocs/futures/en/#new-order-trade

    :param order:
    :return:
    """

    try:
        # todo: надо достовать количество знаков после запятой из бинанс для каждого тикера
        quantity = Decimal(order["quantity"]).quantize(Decimal('1.00000000'), rounding=ROUND_DOWN)
        price = Decimal(order["price"]).quantize(Decimal('1.00000000'), rounding=ROUND_DOWN)

        quantity = float(quantity)
        price = float(price)

        response = client.new_order(
            symbol=order["symbol"],
            type='MARKET',
            quantity=quantity,
            # positionSide='LONG',
            side=order["side"],
            # price=price
        )

        logging.info(f"Order created successfully: {response}")
        return response['orderId']
    except Exception as e:
        logging.error(f"Failed to create order: {e}")
        raise HTTPException(status_code=500, detail="Failed to create order")


async def create_order_futures(order):
    """
    https://binance-docs.github.io/apidocs/futures/en/#new-order-trade

    :param order:
    :return:
    """

    try:
        quantity = Decimal(order["quantity"]).quantize(Decimal('1.00000000'), rounding=ROUND_DOWN)
        price = Decimal(order["price"]).quantize(Decimal('1.00000000'), rounding=ROUND_DOWN)

        quantity = float(quantity)
        price = float(price)

        response = client.new_order(
            symbol=order["symbol"],
            type='MARKET',
            quantity=quantity,
            positionSide='LONG',
            side=order["side"],
            price=price
        )

        logging.info(f"Order created successfully: {response}")
        return response['orderId']
    except Exception as e:
        logging.error(f"Failed to create order: {e}")
        raise HTTPException(status_code=500, detail="Failed to create order")




# async def monitor_order(symbol, order_id):
#     loop = asyncio.get_event_loop()
#     event = asyncio.Event()
#
#     def handle_message(_, message):
#         if message['e'] == 'executionReport' and message['i'] == order_id:
#             if message['X'] == 'FILLED':
#                 logging.info(f"Order {order_id} filled.")
#                 event.set()
#
#     ws_client.start()
#     ws_client.user_data(handle_message)
#     await event.wait()
#     ws_client.stop()
#

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
        order_id = await create_order_futures(order)
        # await monitor_order(order["symbol"], order_id)


@app.post("/webhook/test")
async def receive_webhook(request: Request):
    print(request.__dict__)

    headers = request.headers
    qparams = request.query_params
    pparams = request.path_params

    if 'text/plain' in request.headers['content-type']:
        print("text/plain")
        body = await request.body()
        body = body.decode('utf-8')
        logging.info(f"Received webhook text payload: {body}")

        return {"status": "success"}

    elif 'application/json' in request.headers['content-type']:
        print("application/json")
        payload = await request.json()
        logging.info(f"Received webhook JSON payload: {payload}")

        model = WebhookPayload(**payload)

    else:
        raise HTTPException(status_code=400, detail="Unsupported content type")

    return model.model_dump_json()


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
