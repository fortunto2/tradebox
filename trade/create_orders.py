import json
from decimal import Decimal
import sys
from pprint import pprint

from sqlmodel import SQLModel

sys.path.append('..')
sys.path.append('../core')

from trade.orders.grid import calculate_grid_orders
from core.binance_futures import create_order_binance, check_position
from core.db_async import async_engine
from sqlalchemy.ext.asyncio import AsyncSession

from core.models.orders import Order, OrderPositionSide, OrderType, OrderSide, OrderStatus, OrderBinanceStatus
from core.schemas.webhook import WebhookPayload


async def create_orders_in_db(payload: WebhookPayload, webhook_id, session: AsyncSession):

    position = await check_position(symbol=payload.symbol)
    if position.get('markPrice'):
        mark_price = Decimal(position.get('markPrice', 0))
    else:
        raise ValueError("mark_price not found in position.")

    grid_orders = calculate_grid_orders(payload, mark_price)

    if grid_orders["sufficient_funds"] is False:
        raise ValueError("Недостаточно средств для открытия позиции.")

    # first order by market
    first_quantity = payload.open.amount
    first_order = Order(
        symbol=payload.symbol,
        side=payload.side,
        quantity=first_quantity,
        leverage=payload.open.leverage,
        position_side=OrderPositionSide.LONG,
        type=OrderType.MARKET,
        webhook_id=webhook_id,
        order_number=0
    )

    # приходиться сразу создать ордер в бинанс, чтоб получить цену для расчета
    order_binance_id = await create_order_binance(first_order)
    first_order.binance_id = order_binance_id

    position = await check_position(symbol=payload.symbol)
    if position:
        first_order.price = position['entryPrice']
        first_order.status = OrderStatus.FILLED
        first_order.binance_status = OrderBinanceStatus.FILLED

    pprint(first_order.model_dump())
    session.add(first_order)

    index = 0

    tp_price = Decimal(position['breakEvenPrice']) * (1 + Decimal(payload.settings.tp) / 100)

    # любое измение позиции, если поменялась что нибудь, берем из позиции новый обьем и цену.
    take_proffit_order = Order(
        symbol=payload.symbol,
        side=OrderSide.SELL,
        quantity=position['positionAmt'],
        leverage=payload.open.leverage,
        position_side=OrderPositionSide.LONG,
        type=OrderType.LIMIT,
        webhook_id=webhook_id,
        order_number=0,
        price=tp_price
    )
    # старый надо отменить, запоминать старый.

    pprint(take_proffit_order.model_dump())
    order_binance_id = await create_order_binance(take_proffit_order)

    long_buy_orders = []

    # Создание ордеров по мартигейлу и сетке
    for index, (price, quantity) in enumerate(zip(grid_orders["long_orders"], grid_orders["martingale_orders"])):
        print("-----------------")

        order = Order(
            symbol=payload.symbol,
            side=OrderSide.BUY,
            price=price,
            quantity=quantity,
            leverage=payload.open.leverage,
            position_side=OrderPositionSide.LONG,
            type=OrderType.LIMIT,
            webhook_id=webhook_id,
            order_number=index + 1
        )
        pprint(order.model_dump())
        session.add(order)

        long_buy_orders.append(order)

    order_binance_id = await create_order_binance(long_buy_orders[0])

    # финальный ордер на шорт
    short_order = Order(
        symbol=payload.symbol,
        side=OrderSide.SELL,
        price=grid_orders["short_order_price"],
        quantity=grid_orders["short_order_amount"],
        leverage=payload.open.leverage,
        position_side=OrderPositionSide.SHORT,
        type=OrderType.LIMIT,
        webhook_id=webhook_id,
        order_number=index + 1
    )

    pprint(short_order.model_dump())
    session.add(short_order)

    await session.commit()
    return first_order, grid_orders, short_order


async def main(payload: WebhookPayload, current_price: Decimal = Decimal(0.3634)):
    async with async_engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    async with AsyncSession(async_engine) as session:
        await create_orders_in_db(payload, current_price, session)


if __name__ == "__main__":
    import sys

    sys.path.append('..')
    sys.path.append('../core')

    with open('tests/joe.json', 'r') as file:
        data = json.load(file)

    payload = WebhookPayload(**data)

    # result = calculate_orders(payload, Decimal(0.3634))
    # print(result)

    import asyncio

    # from core.db_async import async_session
    asyncio.run(main(payload, Decimal(0.3634)))
