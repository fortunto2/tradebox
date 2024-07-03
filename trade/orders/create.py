import time
from decimal import Decimal
import sys
from pprint import pprint
from typing import Optional

from sqlmodel.ext.asyncio.session import AsyncSession

from core.db_async import async_engine
from trade.handle_orders import db_get_all_order

sys.path.append('../../core')
sys.path.append('')

from core.schemas.position import LongPosition, ShortPosition
from core.schemas.webhook import WebhookPayload
from core.binance_futures import create_order_binance, check_position, get_order_id, cancel_order_binance
from core.models.orders import Order, OrderPositionSide, OrderType, OrderSide, OrderStatus, OrderBinanceStatus


async def create_market_order(
        symbol: str,
        quantity: Decimal,
        leverage: int,
        webhook_id,
        session: AsyncSession
) -> Order:
    """
    (LONG-BUY-MARKET) - стартовый лонг.
    Создание маркет ордера в самом начале когда пришел вебхук и открыли позицию
    :param symbol:
    :param quantity:
    :param leverage:
    :param webhook_id:
    :param session:
    :return:
    """
    print("Market order:")

    market_order = Order(
        position_side=OrderPositionSide.LONG,
        side=OrderSide.BUY,
        type=OrderType.MARKET,

        symbol=symbol,
        quantity=quantity,
        leverage=leverage,
        webhook_id=webhook_id,
        order_number=0
    )

    order_binance_id = await create_order_binance(market_order)
    market_order.binance_id = order_binance_id

    position_long, _ = await check_position(symbol=symbol)
    position_long: LongPosition

    if position_long:
        market_order.price = position_long.entryPrice
        market_order.status = OrderStatus.FILLED

    # while not Filled
    order = {'status': 'NEW'}

    while order['status'] != 'FILLED':
        order = await get_order_id(symbol, order_binance_id)
        time.sleep(1)
        market_order.binance_status = OrderBinanceStatus.FILLED

    pprint(market_order.model_dump())
    session.add(market_order)

    return market_order


async def create_tp_order(
        symbol: str,
        tp: Decimal,
        leverage: int,
        webhook_id,
        session: AsyncSession
) -> Order:
    """
    (LONG-SELL-TAKE_PROFIT[LIMIT] ) - сверху.
    Создание тейк профит ордера, он постоянно передвигается после
    обновления сетки и создания новых лимитных ордеров.

    Если он сработал, то позицию поидее закрываем.
    Забирем прибыль

    :param symbol:
    :param tp:
    :param leverage:
    :param webhook_id:
    :param session:
    :return:
    """
    print("Take proffit order:")

    # remove old tp orders
    orders = await db_get_all_order(webhook_id, OrderStatus.IN_PROGRESS, OrderType.TAKE_PROFIT, session)
    for order in orders:
        try:
            result = await cancel_order_binance(symbol, order.binance_id)
            if result['status'] == 'CANCELED':
                order.status = OrderStatus.CANCELED
                session.add(order)
        except Exception as e:
            print(e)

    position_long, _ = await check_position(symbol=symbol)
    position_long: LongPosition

    tp_price = Decimal(position_long.breakEvenPrice) * (1 + Decimal(tp) / 100)

    # любое измение позиции, если поменялась что нибудь, берем из позиции новый обьем и цену.
    take_proffit_order = Order(
        position_side=OrderPositionSide.LONG,
        side=OrderSide.SELL,
        type=OrderType.TAKE_PROFIT,

        symbol=symbol,
        quantity=position_long.positionAmt,
        leverage=leverage,
        webhook_id=webhook_id,
        price=tp_price
    )
    # старый надо отменить, запоминать старый.

    take_proffit_order.binance_id = await create_order_binance(take_proffit_order)
    take_proffit_order.status = OrderStatus.IN_PROGRESS

    pprint(take_proffit_order.model_dump())

    session.add(take_proffit_order)

    return take_proffit_order


async def create_limit_order(
        symbol: str,
        price: Decimal,
        quantity: Decimal,
        leverage: int,
        webhook_id,
        session: AsyncSession,
) -> Order:
    """
    (LONG-BUY-LIMIT) - снизу.
    Усредняющие ордера которые постоянно на покупку снизу.
    :param symbol:
    :param price:
    :param quantity:
    :param leverage:
    :param webhook_id:
    :param session:
    :return:
    """
    print("Limit order:")

    limit_order = Order(
        position_side=OrderPositionSide.LONG,
        side=OrderSide.BUY,
        type=OrderType.LIMIT,

        symbol=symbol,
        price=price,
        quantity=quantity,
        leverage=leverage,
        webhook_id=webhook_id,
    )
    limit_order.binance_id = await create_order_binance(limit_order)
    limit_order.status = OrderStatus.IN_PROGRESS

    pprint(limit_order.model_dump())

    session.add(limit_order)

    return limit_order


async def open_hedge_position(
        symbol: str,
        price: Decimal,
        quantity: Decimal,
        leverage: int,
        webhook_id,
        session: AsyncSession
) -> Order:
    """
    (SHORT-SELL-HEDGE_LIMIT) - сверху.

    Страховка, последний ордер который мы ставим как хеджирование.
    Ради этого ордера все и задумано. Он открывает позицию
    :param symbol:
    :param price:
    :param quantity:
    :param leverage:
    :param webhook_id:
    :param session:
    :return:
    """
    print("Final short order:")

    short_order = Order(
        position_side=OrderPositionSide.SHORT,
        side=OrderSide.SELL,
        type=OrderType.HEDGE_LIMIT,

        symbol=symbol,
        price=price,
        quantity=quantity,
        leverage=leverage,
        webhook_id=webhook_id,
    )

    short_order.binance_id = await create_order_binance(short_order)
    short_order.status = OrderStatus.IN_PROGRESS
    pprint(short_order.model_dump())
    session.add(short_order)

    return short_order


async def create_hedge_stop_loss_order(
        symbol: str,
        sl_short: float,
        quantity: Decimal,
        leverage: int,
        webhook_id,
        session: AsyncSession
) -> Order:
    """
    (SHORT-BUY-HEDGE_STOP_LIMIT) - сверху.
    Чтобы когда цена пойдет вверх, он закрыл позицию.
    Если пойдет еще выше цена, шорт будет в 2 раза будет больше чем лонговая.
    Нам надо скинуть эту позицию чтобы дальше шла вверх.

    :param symbol:
    :param sl_short: payload.settings.sl_short
    :param quantity:
    :param leverage:
    :param webhook_id:
    :param session:
    :return:
    """
    print("Final short order:")

    _, position_short = await check_position(symbol=symbol)
    position_short: ShortPosition

    price = Decimal(position_short.entryPrice) * (1 + Decimal(sl_short) / 100)

    order = Order(
        position_side=OrderPositionSide.SHORT,
        side=OrderSide.BUY,
        type=OrderType.HEDGE_STOP_LOSS,

        symbol=symbol,
        price=price,
        quantity=quantity,
        leverage=leverage,
        webhook_id=webhook_id,
    )

    order.binance_id = await create_order_binance(order)
    order.status = OrderStatus.IN_PROGRESS
    pprint(order.model_dump())
    session.add(order)

    return order
