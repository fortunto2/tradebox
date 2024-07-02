from decimal import Decimal
import sys
from pprint import pprint
from typing import Optional

from sqlmodel.ext.asyncio.session import AsyncSession

sys.path.append('../../core')
sys.path.append('')

from core.schemas.position import LongPosition, ShortPosition
from core.schemas.webhook import WebhookPayload
from core.binance_futures import create_order_binance, check_position
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
        market_order.binance_status = OrderBinanceStatus.FILLED

    pprint(market_order.model_dump())
    session.add(market_order)
    await session.commit()

    return market_order


async def create_tp_order(
        symbol: str,
        tp: Decimal,
        leverage: int,
        webhook_id,
        session: AsyncSession
) -> Order:
    """
    (LONG-SELL-LIMIT) - сверху.
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

    position_long, _ = await check_position(symbol=symbol)
    position_long: LongPosition

    tp_price = Decimal(position_long.breakEvenPrice) * (1 + Decimal(tp) / 100)

    # любое измение позиции, если поменялась что нибудь, берем из позиции новый обьем и цену.
    take_proffit_order = Order(
        position_side=OrderPositionSide.LONG,
        side=OrderSide.SELL,
        type=OrderType.LIMIT,

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
    await session.commit()

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
    await session.commit()

    return limit_order


async def create_final_short_order(
        symbol: str,
        price: Decimal,
        quantity: Decimal,
        leverage: int,
        webhook_id,
        session: AsyncSession
) -> Order:
    """
    (SHORT-SELL-LIMIT) - сверху.

    Страховка, последний ордер который мы ставим как хеджирование.
    Ради этого ордера все и задумано.
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
        type=OrderType.LIMIT,

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

    await session.commit()

    return short_order
