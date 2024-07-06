from fastapi import FastAPI, HTTPException, Depends
import logging

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import SQLModel

from core.binance_futures import check_position_side_dual, check_position
from trade.orders.orders_processing import create_first_orders
from core.models.webhook import WebHook
from core.schemas.webhook import WebhookPayload
from core.tg_client import TelegramClient

app = FastAPI()
logging.basicConfig(level=logging.INFO)

from core.db_async import async_engine, get_async_session


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

    # firstly check existing orders
    # open_orders = await check_open_orders(symbol)
    # if open_orders:
    #     logging.info(f"Open orders found for symbol: {symbol}. Ignoring new webhook.")
    #     return {"status": "ignored", "reason": "open orders found"}

    position = await check_position(symbol=body.symbol)
    if float(position.get("entryPrice")) > 0:
        print(position)
        print(f"Position found for symbol: {body.symbol}. Ignoring new webhook.")
        return {"status": "ignored", "reason": f"position found for {body.symbol}"}

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

    # Send the positions data as a string message to Telegram
    tg = TelegramClient()
    message = f"New webhook: {webhook.model_dump_json()}"
    tg.send_message(message=message)

    # current_price = get_current_price(symbol)
    # logging.info(f"Current price for {symbol}: {current_price}")

    await create_first_orders(body, webhook.id, session)
    # tg.send_message(message=first_order.model_dump_json())

    return {"status": "success"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, log_level="info", reload=True)
