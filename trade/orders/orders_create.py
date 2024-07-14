import asyncio
from decimal import Decimal
import sys
from pprint import pprint

sys.path.append('../../core')
sys.path.append('')

from core.views.handle_orders import db_get_all_order

from sqlmodel.ext.asyncio.session import AsyncSession

from core.schemas.position import LongPosition, ShortPosition
from core.binance_futures import create_order_binance, check_position, get_order_id, cancel_order_binance
from core.models.orders import Order, OrderPositionSide, OrderType, OrderSide, OrderStatus, OrderBinanceStatus


async def create_long_market_order(
        symbol: str,
        quantity: Decimal,
        leverage: int,
        webhook_id,
        side: OrderSide = OrderSide.BUY,
        session: AsyncSession = None,
) -> Order:
    """
    (LONG-BUY-MARKET) - стартовый лонг.
    Создание маркет ордера в самом начале когда пришел вебхук и открыли позицию
    :param side:
    :param symbol:
    :param quantity:
    :param leverage:
    :param webhook_id:
    :param session:
    :return:
    """
    print("Market order LONG:")

    market_order = Order(
        position_side=OrderPositionSide.LONG,
        side=side,
        type=OrderType.LONG_MARKET,

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
        await asyncio.sleep(1)
        market_order.binance_status = OrderBinanceStatus.FILLED

    pprint(market_order.model_dump())
    session.add(market_order)
    await session.commit()

    return market_order


async def create_short_market_order(
        symbol: str,
        quantity: Decimal,
        leverage: int,
        webhook_id,
        side: OrderSide = OrderSide.BUY,
        session: AsyncSession = None
) -> Order:
    """
    (SHORT-BUY-MARKET) - вконце для закрытия
    :param side:
    :param symbol:
    :param quantity:
    :param leverage:
    :param webhook_id:
    :param session:
    :return:
    """
    print("Market order SHORT:")

    market_order = Order(
        position_side=OrderPositionSide.SHORT,
        side=side,
        type=OrderType.SHORT_MARKET,

        symbol=symbol,
        quantity=quantity,
        leverage=leverage,
        webhook_id=webhook_id,
        order_number=0
    )

    order_binance_id = await create_order_binance(market_order)
    market_order.binance_id = order_binance_id

    _, position_short = await check_position(symbol=symbol)
    position_short: ShortPosition

    if position_short:
        market_order.price = position_short.entryPrice
        market_order.status = OrderStatus.FILLED

    # while not Filled
    order = {'status': 'NEW'}

    while order['status'] != 'FILLED':
        order = await get_order_id(symbol, order_binance_id)
        await asyncio.sleep(1)
        market_order.binance_status = OrderBinanceStatus.FILLED

    pprint(market_order.model_dump())
    session.add(market_order)
    await session.commit()

    return market_order



async def create_long_tp_order(
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
    orders = await db_get_all_order(webhook_id, OrderStatus.IN_PROGRESS, OrderType.LONG_TAKE_PROFIT, session)
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
        type=OrderType.LONG_TAKE_PROFIT,

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


async def create_long_limit_order(
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
    print("LONG-BUY-LIMIT order:")

    limit_order = Order(
        position_side=OrderPositionSide.LONG,
        side=OrderSide.BUY,
        type=OrderType.LONG_LIMIT,

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


async def create_short_stop_order(
        symbol: str,
        price: Decimal,
        quantity: Decimal,
        leverage: int,
        webhook_id,
        session: AsyncSession
) -> Order:
    """
    (SHORT-SELL) - ограничивающий стоп-ордер.
    Этот тип ордера используется для установки предела убытка, предотвращая дальнейшие потери.
    :param symbol: Тикер символа
    :param price: Цена, по которой будет активирован стоп-ордер
    :param quantity: Количество, которое нужно продать или купить
    :param leverage: Плечо
    :param webhook_id: Идентификатор вебхука
    :param session: Сессия базы данных
    :return: Созданный ордер
    """
    print("Creating SHORT STOP order:")

    # Создание объекта ордера
    limit_stop_order = Order(
        position_side=OrderPositionSide.SHORT,
        side=OrderSide.SELL,
        type=OrderType.SHORT_LIMIT,

        symbol=symbol,
        price=price,
        quantity=quantity,
        leverage=leverage,
        webhook_id=webhook_id,
    )

    # Отправка ордера на биржу и получение ID
    limit_stop_order.binance_id = await create_order_binance(limit_stop_order)
    limit_stop_order.status = OrderStatus.IN_PROGRESS

    pprint(limit_stop_order.model_dump())
    session.add(limit_stop_order)
    await session.commit()

    return limit_stop_order


async def create_short_stop_loss_order(
        symbol: str,
        sl_short: float,
        leverage: int,
        webhook_id,
        session: AsyncSession
) -> Order:
    """
    (SHORT-BUY) - сверху.
    Чтобы когда цена пойдет вверх, он закрыл позицию.
    Если пойдет еще выше цена, шорт будет в 2 раза будет больше чем лонговая.
    Нам надо скинуть эту позицию чтобы дальше шла вверх.

    :param price:
    :param symbol:
    :param sl_short: payload.settings.sl_short
    :param quantity:
    :param leverage:
    :param webhook_id:
    :param session:
    :return:
    """
    print("SHORT-BUY:")

    _, position_short = await check_position(symbol=symbol)
    position_short: ShortPosition

    price = Decimal(position_short.entryPrice) * (1 + Decimal(sl_short) / 100)
    quantity = abs(position_short.positionAmt)
    print('price:', price)
    print('quantity:', quantity)

    order = Order(
        position_side=OrderPositionSide.SHORT,
        side=OrderSide.BUY,
        type=OrderType.SHORT_STOP_LOSS,

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
    await session.commit()

    return order
