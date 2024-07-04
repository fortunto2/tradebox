import asyncio
import json
from decimal import Decimal
import sys
from pprint import pprint
from random import random, randint
from typing import List

from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from core.models.orders import Order, OrderType, OrderStatus
from core.schemas.position import ShortPosition, LongPosition
from trade.handle_orders import db_get_last_order

sys.path.append('..')
sys.path.append('../core')

from trade.orders.grid import update_grid
from core.db_async import async_engine

from core.schemas.webhook import WebhookPayload
from trade.orders.create import create_market_order, create_tp_order, create_limit_order, \
    create_hedge_stop_loss_order, open_hedge_position
from core.binance_futures import wait_order_id, check_all_orders, get_position_closed_pnl, \
    check_position


def wait_limit_order_filled(symbol, order_id):
    wait_order_id(
        symbol=symbol,
        order_id=order_id
    )


async def get_market_orders(payload: WebhookPayload, webhook_id, session: AsyncSession):
    order_binance_id = None
    if webhook_id:
        order = await db_get_last_order(webhook_id, session, OrderType.MARKET)
        order_binance_id = order.binance_id

    orders: List[dict] = await check_all_orders(
        symbol=payload.symbol,
        orderId=order_binance_id
    )

    limit_orders = []
    for order in orders:
        # select just  (LONG-BUY-LIMIT)
        if order["type"] == "LIMIT" and order["side"] == "BUY" and order["positionSide"] == "LONG":
            limit_orders.append(order)

    print(limit_orders)

    return limit_orders


async def create_orders_in_db(payload: WebhookPayload, webhook_id, session: AsyncSession):
    # todo check in db first
    first_order = await create_market_order(
        symbol=payload.symbol,
        quantity=payload.open.amount,
        leverage=payload.open.leverage,
        webhook_id=webhook_id,
        session=session
    )

    await session.commit()

    grid_orders = await update_grid(payload, webhook_id, session)

    # check in дб и binance - сколько уже размещено ордеров

    # Создание ордеров по мартигейлу и сетке
    for index, (price, quantity) in enumerate(zip(grid_orders["long_orders"], grid_orders["martingale_orders"])):
        print("-----------------")

        # надо сперва еще проверять что его нет
        tp_order = await create_tp_order(
            symbol=payload.symbol,
            tp=payload.settings.tp,
            leverage=payload.open.leverage,
            webhook_id=webhook_id,
            session=session,
        )

        limit_order = await create_limit_order(
            symbol=payload.symbol,
            price=price,
            quantity=quantity,
            leverage=payload.open.leverage,
            webhook_id=webhook_id,
            session=session,
        )

        binance_order = await wait_order_id(
            symbol=payload.symbol,
            order_id=limit_order.binance_id
        )

        limit_order.binance_status = binance_order["status"]
        limit_order.status = OrderStatus.FILLED

        await session.commit()

    # только один раз, когда хватает денег
    hedge_order = await open_hedge_position(
        symbol=payload.symbol,
        price=grid_orders["short_order_price"],
        quantity=grid_orders["short_order_amount"],
        leverage=payload.open.leverage,
        webhook_id=webhook_id,
        session=session,
    )
    # todo: как открылась позиция шорт, надо теперь запустить слежение за обоими позициями - шорт и лонг

    binance_hedge_order = await wait_order_id(
        symbol=payload.symbol,
        order_id=hedge_order.binance_id
    )
    hedge_order.status = OrderStatus.FILLED
    hedge_order.binance_status = binance_hedge_order["status"]
    await session.commit()

    # quantity - в цикле уменьшеается, вычитаем убытки
    # todo: следить за статусом, когда он исполниться, чтобы выставить опять открыть заново хедже позицию
    hedge_stop_loss_order = await create_hedge_stop_loss_order(
        symbol=payload.symbol,
        sl_short=payload.settings.sl_short,
        leverage=payload.open.leverage,
        webhook_id=webhook_id,
        session=session,
        quantity=grid_orders["short_order_amount"]
    )
    binance_hedge_stop_loss_order = await wait_order_id(
        symbol=payload.symbol,
        order_id=hedge_stop_loss_order.binance_id
    )
    # todo: ждем или это или вебсокет
    hedge_stop_loss_order.status = OrderStatus.FILLED
    hedge_stop_loss_order.binance_status = binance_hedge_stop_loss_order["status"]

    hedge_price = Decimal(grid_orders["short_order_price"]) * (1 - Decimal(payload.settings.offset_pluse) / 100)

    await session.commit()
    #
    # while True:
    #
    #     pnl = get_position_closed_pnl(payload.symbol, int(hedge_stop_loss_order.binance_id))
    #     print("pnl:", pnl)
    #
    #     position_long, position_short = await check_position(symbol=payload.symbol)
    #     position_short: ShortPosition
    #     position_long: LongPosition
    #
    #     extramarg = Decimal(payload.settings.extramarg) - pnl
    #
    #     if extramarg * Decimal(payload.open.leverage) < 11:
    #         #  проверку что не extramarg не должен быть менее 11 долларов * плече
    #         break
    #
    #     quantity = extramarg * Decimal(payload.open.leverage) / hedge_price
    #
    #     # только один раз, когда хватает денег
    #     hedge_order = await open_hedge_position(
    #         symbol=payload.symbol,
    #         price=hedge_price,
    #         quantity=quantity,
    #         leverage=payload.open.leverage,
    #         webhook_id=webhook_id,
    #         session=session,
    #     )
    #
    #     hedge_price = Decimal(position_short.entryPrice) * (1 - Decimal(payload.settings.offset_pluse) / 100)
    #
    #     hedge_stop_loss_order = await create_hedge_stop_loss_order(
    #         symbol=payload.symbol,
    #         sl_short=payload.settings.sl_short,
    #         leverage=payload.open.leverage,
    #         webhook_id=webhook_id,
    #         session=session,
    #         quantity=quantity
    #     )

    return


async def main(payload: WebhookPayload):
    async with async_engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    async with AsyncSession(async_engine) as session:
        # webhook = await save_webhook(payload, session)

        wh_id = randint(1, 1000)

        await create_orders_in_db(payload, wh_id, session)
        # await get_position_closed_pnl('JOEUSDT')


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
