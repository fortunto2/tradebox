from decimal import Decimal
import sys
from pprint import pprint
import time

from core.schemas.position import LongPosition, ShortPosition
from core.binance_futures import create_order_binance, check_position, get_order_id, cancel_order_binance
from core.models.orders import Order, OrderPositionSide, OrderType, OrderSide, OrderStatus, OrderBinanceStatus
from core.views.handle_orders import db_get_all_order
from core.db_sync import execute_sqlmodel_query, execute_sqlmodel_query_single

sys.path.append('../../core')
sys.path.append('')


def create_long_market_order(
        symbol: str,
        quantity: Decimal,
        leverage: int,
        webhook_id,
        side: OrderSide = OrderSide.BUY
) -> Order:
    print("Market order LONG:")

    def create_order(session):
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

        order_binance_id = create_order_binance(market_order)
        market_order.binance_id = order_binance_id

        # убрать отсюад, в вебсокеты
        position_long, _ = check_position(symbol=symbol)
        position_long: LongPosition

        if position_long:
            market_order.price = position_long.entryPrice
            market_order.status = OrderStatus.FILLED

        market_order.binance_status = OrderBinanceStatus.FILLED

        pprint(market_order.model_dump())
        session.add(market_order)
        session.commit()
        return market_order

    return execute_sqlmodel_query_single(create_order)


def create_short_market_order(
        symbol: str,
        quantity: Decimal,
        leverage: int,
        webhook_id,
        side: OrderSide = OrderSide.BUY
) -> Order:
    print("Market order SHORT:")


    def create_order(session):
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

        order_binance_id = create_order_binance(market_order)
        market_order.binance_id = order_binance_id

        _, position_short = check_position(symbol=symbol)
        position_short: ShortPosition

        if position_short:
            market_order.price = position_short.entryPrice
            market_order.status = OrderStatus.FILLED

        market_order.binance_status = OrderBinanceStatus.FILLED

        pprint(market_order.model_dump())
        session.add(market_order)
        session.commit()
        return market_order

    return execute_sqlmodel_query_single(create_order)


def create_long_tp_order(
        symbol: str,
        tp: Decimal,
        leverage: int,
        webhook_id
) -> Order:
    print("Take profit order:")

    def create_order(session):
        orders = db_get_all_order(webhook_id, OrderStatus.IN_PROGRESS, OrderType.LONG_TAKE_PROFIT)
        for order in orders:
            try:
                result = cancel_order_binance(symbol, order.binance_id)
                if result['status'] == 'CANCELED':
                    order.status = OrderStatus.CANCELED
                    session.add(order)
            except Exception as e:
                print(e)

        position_long, _ = check_position(symbol=symbol)
        position_long: LongPosition

        tp_price = Decimal(position_long.breakEvenPrice) * (1 + Decimal(tp) / 100)

        take_profit_order = Order(
            position_side=OrderPositionSide.LONG,
            side=OrderSide.SELL,
            type=OrderType.LONG_TAKE_PROFIT,
            symbol=symbol,
            quantity=position_long.positionAmt,
            leverage=leverage,
            webhook_id=webhook_id,
            price=tp_price
        )

        take_profit_order.binance_id = create_order_binance(take_profit_order)
        take_profit_order.status = OrderStatus.IN_PROGRESS

        pprint(take_profit_order.model_dump())
        session.add(take_profit_order)
        session.commit()
        return take_profit_order

    return execute_sqlmodel_query_single(create_order)


def create_long_limit_order(
        symbol: str,
        price: Decimal,
        quantity: Decimal,
        leverage: int,
        webhook_id
) -> Order:
    print("LONG-BUY-LIMIT order:")

    def create_order(session):
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
        limit_order.binance_id = create_order_binance(limit_order)
        limit_order.status = OrderStatus.IN_PROGRESS

        pprint(limit_order.model_dump())

        session.add(limit_order)
        session.commit()
        return limit_order

    return execute_sqlmodel_query_single(create_order)


def create_short_stop_order(
        symbol: str,
        price: Decimal,
        quantity: Decimal,
        leverage: int,
        webhook_id
) -> Order:
    print("Creating SHORT STOP order:")

    def create_order(session):
        order = Order(
            position_side=OrderPositionSide.SHORT,
            side=OrderSide.SELL,
            type=OrderType.SHORT_LIMIT,
            symbol=symbol,
            price=price,
            quantity=quantity,
            leverage=leverage,
            webhook_id=webhook_id,
        )

        order_binance = None
        timer = 0

        order.binance_id = create_order_binance(order)
        order.status = OrderStatus.IN_PROGRESS

        while not order_binance or timer < 10:

            try:
                order_binance = get_order_id(symbol, order.binance_id)
                order.binance_status = order_binance['status']
            except Exception as e:
                print(e)
                timer += 1

            if not order_binance:
                print('!!!!Order not found, retrying')
                time.sleep(5)

        pprint(order.model_dump())

        session.add(order)
        session.commit()
        return order

    return execute_sqlmodel_query_single(create_order)


def create_short_stop_loss_order(
        symbol: str,
        sl_short: float,
        leverage: int,
        webhook_id
) -> Order:
    print("SHORT-BUY:")

    def create_order(session):
        _, position_short = check_position(symbol=symbol)
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

        order_binance = None
        timer = 0

        order.binance_id = create_order_binance(order)
        order.status = OrderStatus.IN_PROGRESS
        pprint(order.model_dump())

        while not order_binance or timer < 10:

            try:
                order_binance = get_order_id(symbol, order.binance_id)
                order.binance_status = order_binance['status']
            except Exception as e:
                print(e)

            if not order_binance:
                print('!!!!Order not found, retrying')
                time.sleep(5)
                timer += 1

        session.add(order)
        session.commit()
        return order

    return execute_sqlmodel_query_single(create_order)
