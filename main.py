from fastapi import FastAPI, Request, HTTPException
import logging

from tg_client import TelegramClient

from fastapi import FastAPI, Request, HTTPException
from pydantic import BaseModel, ValidationError
import logging
import requests

app = FastAPI()
logging.basicConfig(level=logging.INFO)


# Define Pydantic models for webhook validation
class OpenOrder(BaseModel):
    enabled: bool
    amountType: str
    amount: str
    leverage: str


class DCAOrder(BaseModel):
    enabled: bool
    amountType: str
    amount: str


class WebhookPayload(BaseModel):
    name: str
    secret: str
    side: str
    positionSide: str
    symbol: str
    open: OpenOrder
    dca: DCAOrder


# Global state to keep track of open positions
positions = {}

app = FastAPI()

logging.basicConfig(level=logging.INFO)


@app.post("/webhook")
async def receive_webhook(request: Request):
    print(request.__dict__)

    headers = request.headers
    qparams = request.query_params
    pparams = request.path_params

    if 'text/plain' in request.headers['content-type']:
        body = await request.body()
        body = body.decode('utf-8')
        logging.info(f"Received webhook text payload: {body}")

        tg = TelegramClient()
        tg.send_message(message=body)

        return {"status": "success"}

    elif 'application/json' in request.headers['content-type']:
        payload = await request.json()
        logging.info(f"Received webhook JSON payload: {payload}")
    else:
        raise HTTPException(status_code=400, detail="Unsupported content type")

    try:
        validated_payload = WebhookPayload(**payload)
    except ValidationError as e:
        logging.error(f"Validation error: {e}")
        raise HTTPException(status_code=400, detail="Invalid webhook payload")

    symbol = validated_payload.symbol

    # Check if there's already an open position for the symbol
    if symbol in positions:
        logging.info(f"Position already open for symbol: {symbol}. Ignoring new webhook.")
        return {"status": "ignored", "reason": "position already open"}

    # Process the webhook and open a new position
    # open_position(validated_payload)

    # Save the position state
    positions[symbol] = {
        "side": validated_payload.side,
        "symbol": validated_payload.symbol,
        "amount": validated_payload.open.amount,
        "leverage": validated_payload.open.leverage,
    }

    tg = TelegramClient()
    tg.send_message(message=positions)

    return {"status": "success"}

        # except Exception as e:
        #     logging.error(f"An error occurred: {e}")
        #     raise HTTPException(status_code=500, detail="Internal server error")
