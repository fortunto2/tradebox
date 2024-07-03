import asyncio
import json
from decimal import Decimal
import sys
from pprint import pprint

from sqlmodel import SQLModel

sys.path.append('..')
sys.path.append('../core')

from trade.orders.grid import update_grid
from core.db_async import async_engine, async_session, get_async_session
from sqlalchemy.ext.asyncio import AsyncSession

from core.schemas.webhook import WebhookPayload
from trade.orders.create import create_market_order, create_tp_order, create_limit_order, create_final_short_order


async def create_orders_in_db(payload: WebhookPayload, webhook_id, session: AsyncSession):

    # todo check in db first
    first_order = await create_market_order(
        symbol=payload.symbol,
        quantity=payload.open.amount,
        leverage=payload.open.leverage,
        webhook_id=webhook_id,
        session=session
    )

    grid_orders = await update_grid(payload, webhook_id, session)

    # check in дб и binance - сколько уже размещено ордеров

    # Создание ордеров по мартигейлу и сетке
    for index, (price, quantity) in enumerate(zip(grid_orders["long_orders"], grid_orders["martingale_orders"])):
        print("-----------------")

        limit_order = await create_limit_order(
            symbol=payload.symbol,
            price=price,
            quantity=quantity,
            leverage=payload.open.leverage,
            webhook_id=webhook_id,
            session=session,
        )

        # wait_limit_order_filled()

        # надо сперва еще проверять что его нет
        tp_order = await create_tp_order(
            symbol=payload.symbol,
            tp=payload.settings.tp,
            leverage=payload.open.leverage,
            webhook_id=webhook_id,
            session=session,
        )


    # финальный ордер на шорт
    short_order = await create_final_short_order(
        symbol=payload.symbol,
        price=grid_orders["short_order_price"],
        quantity=grid_orders["short_order_amount"],
        leverage=payload.open.leverage,
        webhook_id=webhook_id,
        session=session,
    )

    return first_order, grid_orders, short_order


async def main(payload: WebhookPayload):
    async with async_engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    async with AsyncSession(async_engine) as session:
        # webhook = await save_webhook(payload, session)

        await create_orders_in_db(payload, 1, session)


if __name__ == "__main__":
    import sys
    from core.models.webhook import WebHook, save_webhook

    sys.path.append('..')
    sys.path.append('../core')

    with open('tests/joe.json', 'r') as file:
        data = json.load(file)

    payload = WebhookPayload(**data)

    # from core.db_async import async_session
    asyncio.run(main(payload))
