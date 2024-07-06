import time
from decimal import Decimal
import sys
from pprint import pprint

sys.path.append('../../core')
sys.path.append('')

from core.models.webhook import WebHook
from core.schemas.webhook import WebhookPayload
from core.views.handle_orders import db_get_all_order, get_webhook
from typing import List

from sqlmodel.ext.asyncio.session import AsyncSession

from core.views.handle_orders import db_get_last_order, db_get_orders, get_webhook

from trade.orders.grid import update_grid

from core.schemas.position import LongPosition, ShortPosition
from core.binance_futures import create_order_binance, check_position, get_order_id, cancel_order_binance, \
    get_position_closed_pnl, wait_order_id, check_all_orders
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
    print("LONG-BUY-LIMIT order:")

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
    print("SHORT-SELL-HEDGE_LIMIT:")

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
    print("SHORT-BUY-HEDGE_STOP_LIMIT:")

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


async def create_first_orders(payload: WebhookPayload, webhook_id, session: AsyncSession):
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


def wait_limit_order_filled(symbol, order_id):
    wait_order_id(
        symbol=symbol,
        order_id=order_id
    )
