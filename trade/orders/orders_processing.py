from decimal import Decimal
from typing import List

from sqlmodel.ext.asyncio.session import AsyncSession

from core.binance_futures import get_position_closed_pnl, check_position, check_all_orders, wait_order_id
from core.db_async import async_engine
from core.models.orders import OrderType, OrderStatus, OrderPositionSide, OrderSide, OrderBinanceStatus, Order
from core.models.webhook import WebHook
from core.schemas.position import ShortPosition

from core.schemas.webhook import WebhookPayload
from core.views.handle_orders import db_get_last_order, db_get_orders, get_webhook
from trade.orders.grid import update_grid
from trade.orders.orders_create import create_long_market_order,  \
    create_long_tp_order, create_long_limit_order, create_short_stop_order


async def open_long_position(payload: WebhookPayload, webhook_id, session: AsyncSession):
    # todo check in db first
    first_order = await create_long_market_order(
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


async def open_short_position_loop(
        payload: WebhookPayload,
        webhook_id,
        session: AsyncSession,
        order_binance_id: int,
):
    extramarg = Decimal(payload.settings.extramarg)

    # quantity - в цикле уменьшеается, вычитаем убытки

    pnl = get_position_closed_pnl(payload.symbol, int(order_binance_id))
    print("pnl:", pnl)

    extramarg = Decimal(payload.settings.extramarg) + pnl

    if extramarg * Decimal(payload.open.leverage) < 11:
        #  проверку что не extramarg не должен быть менее 11 долларов * плече
        print("Not enough money")
        return

    # _, position_short = await check_position(symbol=payload.symbol)
    # position_short: ShortPosition

    short_order: Order = await db_get_last_order(webhook_id, session, OrderType.SHORT_LIMIT, order_by='ask')

    hedge_price = Decimal(short_order.price) * (1 - Decimal(payload.settings.offset_pluse) / 100)

    quantity = extramarg * Decimal(payload.open.leverage) / hedge_price

    # только один раз, когда хватает денег
    hedge_stop_order = await create_short_stop_order(
        symbol=payload.symbol,
        price=hedge_price,
        quantity=quantity,
        leverage=payload.open.leverage,
        webhook_id=webhook_id,
        session=session,
    )

    return hedge_stop_order.binance_id



#
# async def get_market_orders(payload: WebhookPayload, webhook_id, session: AsyncSession):
#     order_binance_id = None
#     if webhook_id:
#         order = await db_get_last_order(webhook_id, session, OrderType.MARKET)
#         order_binance_id = order.binance_id
#
#     orders: List[dict] = await check_all_orders(
#         symbol=payload.symbol,
#         orderId=order_binance_id
#     )
#
#     limit_orders = []
#     for order in orders:
#         # select just  (LONG-BUY-LIMIT)
#         if order["type"] == "LIMIT" and order["side"] == "BUY" and order["positionSide"] == "LONG":
#             limit_orders.append(order)
#
#     print(limit_orders)
#
#     return limit_orders


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
    if webhook_id:
        orders = await db_get_orders(
            webhook_id=webhook_id,
            order_status=status,
            position_side=OrderPositionSide.LONG,
            order_type=OrderType.LONG_LIMIT,
            order_side=OrderSide.BUY,
            session=session
        )
    else:
        orders = await db_get_orders(
            order_status=status,
            position_side=OrderPositionSide.LONG,
            order_type=OrderType.LONG_LIMIT,
            order_side=OrderSide.BUY,
            session=session
        )

    limit_orders = []

    # order_binance: List[dict] = await check_all_orders(
    #     symbol=symbol,
    #     orderId=orders[0].binance_id
    # )
    # filter by status Filled
    # order_binance_filled = [order for order in order_binance if order["status"] == "FILLED"]

    # for order_bi in order_binance:
    #
    #     # load from enum OrderStatus
    #     order_binance_status = OrderBinanceStatus(order_bi["status"])
    #
    #     if order_binance_status == order.binance_status:
    #         limit_orders.append(order)
    #     else:
    #         order.binance_status = order_binance_status
    #         # select from order_binance["status"]
    #         order.status = OrderStatus(order_bi["status"])

    return orders


async def check_orders_in_the_grid(payload: WebhookPayload, webhook_id, session: AsyncSession):
    grid_orders = await update_grid(payload, webhook_id, session)

    grid = list(zip(grid_orders["long_orders"], grid_orders["martingale_orders"]))
    print(f"grid_orders: {len(grid)}")

    # ищем уже созданные в базе выполненные ордера
    filled_orders = await get_grid_orders(
        symbol=payload.symbol,
        status=OrderStatus.FILLED,
        webhook_id=webhook_id,
        session=session)

    print(f"filled_orders: {len(filled_orders)}")

    return filled_orders, grid_orders, grid


async def grid_make_limit_and_tp_order(
        webhook_id,
        payload: WebhookPayload,
        session: AsyncSession = None):
    """

    :param payload:
    :param webhook_id:
    :param session:
    :return: Вернет True если есть еще ордера в сетке, False если последний ордер
    """

    if not payload:
        print("payload not found, webhook_id:", webhook_id)
        return False

    filled_orders, grid_orders, grid = await check_orders_in_the_grid(payload, webhook_id, session)
    if len(filled_orders) >= len(grid):
        # когда последний заканчивет сетку
        print(f"stop: filled_orders {filled_orders} >= grid_orders {grid_orders}")
        return False

    price, quantity = grid[len(filled_orders)]

    tp_order = await create_long_tp_order(
        symbol=payload.symbol,
        tp=payload.settings.tp,
        leverage=payload.open.leverage,
        webhook_id=webhook_id,
        session=session,
    )

    limit_order = await create_long_limit_order(
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

        short_order_price = Decimal(price) * Decimal(1 - payload.settings.offset_short / 100)
        short_order_amount = Decimal(payload.settings.extramarg * payload.open.leverage) / short_order_price

        await create_short_stop_order(
            symbol=payload.symbol,
            price=short_order_price,
            quantity=short_order_amount,
            leverage=payload.open.leverage,
            webhook_id=webhook_id,
            session=session,
        )

    await session.commit()

    return True


def wait_limit_order_filled(symbol, order_id):
    wait_order_id(
        symbol=symbol,
        order_id=order_id
    )


async def main():
    async with AsyncSession(async_engine) as session:
        orders = await get_grid_orders("JOEUSDT", OrderStatus.FILLED, 7, session)


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
