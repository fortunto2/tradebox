import asyncio
import json
from decimal import Decimal
import sys
from pprint import pprint
from random import random, randint
from typing import List

from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from core.models.orders import Order, OrderType, OrderStatus, OrderPositionSide, OrderSide, OrderBinanceStatus
from core.schemas.position import ShortPosition, LongPosition
from trade.handle_orders import db_get_last_order, db_get_all_order, db_get_orders, get_webhook

sys.path.append('..')
sys.path.append('../core')

from trade.orders.grid import update_grid
from core.db_async import async_engine, async_session

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


async def get_grid_orders(
        symbol: str,
        status: OrderStatus = OrderStatus.FILLED,
        webhook_id=None,
        session: AsyncSession = None,

):
    """
    Ищем в базе все ордера которые уже исполнились из сетки и сверяем статусы с бинанс.

    OrderPositionSide.LONG,
    side=OrderSide.BUY,
    type=OrderType.LIMIT,

    :param symbol:
    :param status:
    :param webhook_id:
    :param session:
    :return:
    """

    if not session:
        # session = AsyncSession(async_engine)
        session = async_session

    if webhook_id:
        orders = await db_get_orders(
            webhook_id=webhook_id,
            order_status=status,
            position_side=OrderPositionSide.LONG,
            order_type=OrderType.LIMIT,
            order_side=OrderSide.BUY,
            session=session
        )
    else:
        orders = await db_get_orders(
            order_status=status,
            position_side=OrderPositionSide.LONG,
            order_type=OrderType.LIMIT,
            order_side=OrderSide.BUY,
            session=session
        )

    limit_orders = []
    for order in orders:
        order_binance: List[dict] = await check_all_orders(
            symbol=symbol,
            orderId=order.binance_id
        )

        for order_bi in order_binance:

            # load from enum OrderStatus
            order_binance_status = OrderBinanceStatus(order_bi["status"])

            if order_binance_status == order.binance_status:
                limit_orders.append(order)
            else:
                order.binance_status = order_binance_status
                # select from order_binance["status"]
                order.status = OrderStatus(order_bi["status"])

    # print(limit_orders)

    return limit_orders


async def grid_make_limit_and_tp_order(
        webhook_id,
        payload: WebhookPayload = None,
        session: AsyncSession = None):
    """

    :param payload:
    :param webhook_id:
    :param session:
    :return: Вернет True если есть еще ордера в сетке, False если последний ордер
    """

    if not session:
        # session = AsyncSession(async_engine)
        session = async_session

    if not payload:
        # get payload from db by webhook_id
        webhook: WebHook = await get_webhook(webhook_id=webhook_id, session=session)
        payload = WebhookPayload(**webhook.model_dump())

    grid_orders = await update_grid(payload)

    grid = list(zip(grid_orders["long_orders"], grid_orders["martingale_orders"]))
    print(f"grid_orders: {len(grid)}")

    # ищем уже созданные в базе выполненные ордера
    filled_orders = await get_grid_orders(
        symbol=payload.symbol,
        status=OrderStatus.FILLED,
        webhook_id=webhook_id,
        session=session)

    print(f"filled_orders: {len(filled_orders)}")

    if len(filled_orders) >= len(grid):
        # когда последний заканчивет сетку
        print(f"stop: filled_orders {filled_orders} >= grid_orders {grid_orders}")
        return False

    price, quantity = grid[len(filled_orders)]

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

    if len(filled_orders) == len(grid) - 1:
        # предпоследний ордер запускается вместе с хедж шорт
        # todo: только один раз, когда хватает денег
        await make_hedge_by_pnl(
            payload=payload,
            webhook_id=webhook_id,
            session=session,
            quantity=grid_orders["short_order_amount"],
            hedge_price=grid_orders["short_order_price"]
        )

    await session.commit()

    return True


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

    # первый запуск создание пары ордеров лимитных по сетки
    await grid_make_limit_and_tp_order(
        webhook_id=webhook_id,
        payload=payload,
        session=session
    )

    return


async def make_hedge_by_pnl(
        payload: WebhookPayload,
        webhook_id,
        session: AsyncSession,
        hedge_stop_loss_order_binance_id: int = None,
        quantity: Decimal = None,
        hedge_price: Decimal = None,
):
    extramarg = Decimal(payload.settings.extramarg)

    if hedge_stop_loss_order_binance_id:
        # quantity - в цикле уменьшеается, вычитаем убытки

        pnl = get_position_closed_pnl(payload.symbol, int(hedge_stop_loss_order_binance_id))
        print("pnl:", pnl)

        extramarg = Decimal(payload.settings.extramarg) - pnl

        if extramarg * Decimal(payload.open.leverage) < 11:
            #  проверку что не extramarg не должен быть менее 11 долларов * плече
            print("Not enough money")
            return

    if not hedge_price:
        _, position_short = await check_position(symbol=payload.symbol)
        position_short: ShortPosition

        hedge_price = Decimal(position_short.entryPrice) * (1 - Decimal(payload.settings.offset_pluse) / 100)

    if not quantity:
        quantity = extramarg * Decimal(payload.open.leverage) / hedge_price

    # только один раз, когда хватает денег
    hedge_order = await open_hedge_position(
        symbol=payload.symbol,
        price=hedge_price,
        quantity=quantity,
        leverage=payload.open.leverage,
        webhook_id=webhook_id,
        session=session,
    )

    hedge_stop_loss_order = await create_hedge_stop_loss_order(
        symbol=payload.symbol,
        sl_short=payload.settings.sl_short,
        leverage=payload.open.leverage,
        webhook_id=webhook_id,
        session=session,
        quantity=quantity
    )

    return hedge_stop_loss_order.binance_id


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
