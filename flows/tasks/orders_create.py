import logging
from decimal import Decimal
import sys
from pprint import pprint
from time import sleep

from prefect import task
from sqlalchemy.orm import joinedload

from core.models.binance_position import BinancePosition
from core.schemas.position import LongPosition
from core.schemas.webhook import WebhookPayload
from core.views.handle_positions import get_exist_position, open_position_task
from flows.tasks.binance_futures import create_order_binance, check_position, cancel_order_binance, get_order_id
from core.models.orders import Order, OrderPositionSide, OrderType, OrderSide, OrderStatus, OrderBinanceStatus
from core.views.handle_orders import db_get_all_order
from core.clients.db_sync import execute_sqlmodel_query_single

sys.path.append('../../core')
sys.path.append('')


# @task
def create_long_market_order(
        symbol: str,
        quantity: Decimal,
        leverage: int,
        webhook_id,
        side: OrderSide = OrderSide.BUY,
        payload: WebhookPayload = None
) -> Order:
    print("create_long_market_order:")

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
        if side == OrderSide.BUY:
            market_order.binance_id = order_binance_id
            market_order.binance_status = OrderBinanceStatus.NEW

            try:
                session.commit()
            except Exception as e:
                logging.error(f"Create order error: {e}")
                return None

            return market_order.id

    return execute_sqlmodel_query_single(create_order)


# @task
def create_short_market_order(
        symbol: str,
        quantity: Decimal,
        leverage: int,
        webhook_id,
        side: OrderSide = OrderSide.SELL
):
    def create_order(session):
        # Check existing position
        _, position_short = check_position(symbol=symbol)

        if not position_short or position_short.positionAmt == 0:
            logging.error(f"No open short position to reduce for symbol: {symbol}")
            return None

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
        if side == OrderSide.SELL:
            market_order.binance_id = order_binance_id
            market_order.binance_status = OrderBinanceStatus.NEW

            try:
                session.commit()
            except Exception as e:
                logging.error(f"Create order error: {e}")
                return None

            return market_order.id

    return execute_sqlmodel_query_single(create_order)


def cancel_in_progress_orders(symbol, webhook_id, order_type: OrderType):
    orders = db_get_all_order(webhook_id, OrderStatus.IN_PROGRESS, order_type)
    for order in orders:
        try:
            result = cancel_order_binance(symbol, order.binance_id)
            if result['status'] == 'CANCELED':
                order.status = OrderStatus.CANCELED
        except Exception as e:
            print(e)
            logging.error(f"Error canceling order: {e}")


@task
def create_long_tp_order(
        symbol: str,
        tp: Decimal,
        leverage: int,
        webhook_id,
        position: BinancePosition = None
) -> Order:
    print("create_long_tp_order:")

    def create_order(session):
        cancel_in_progress_orders(symbol, webhook_id, OrderType.LONG_TAKE_PROFIT)

        if not position:
            position_long, _ = check_position(symbol=symbol)
            position_long: LongPosition

            long_entry = position_long.entryPrice
            long_qty = position_long.positionAmt
        else:
            # todo: тут возможно надо всетак загружать из базы еще раз
            long_entry = position.calculate_adjusted_break_even_price()
            long_qty = position.position_qty

        tp_price = Decimal(long_entry) * (1 + Decimal(tp) / 100)

        take_profit_order = Order(
            position_side=OrderPositionSide.LONG,
            side=OrderSide.SELL,
            type=OrderType.LONG_TAKE_PROFIT,
            symbol=symbol,
            quantity=long_qty,
            leverage=leverage,
            webhook_id=webhook_id,
            price=tp_price
        )

        take_profit_order.binance_id = create_order_binance(take_profit_order)
        take_profit_order.status = OrderStatus.NEW

        pprint(take_profit_order.model_dump())
        select_order: Order = session.query(Order).filter(Order.binance_id == take_profit_order.binance_id).first()
        if not select_order:
            binance_position = get_exist_position(
                symbol=symbol,
                webhook_id=webhook_id,
                position_side=OrderPositionSide.LONG
            )
            if binance_position:
                take_profit_order.binance_position = binance_position

            session.add(take_profit_order)
            session.commit()
        else:
            logging.warning(f"Order already exists: {take_profit_order.binance_id}")
            select_order.status = OrderStatus.IN_PROGRESS
            select_order.type = OrderType.LONG_TAKE_PROFIT
            select_order.price = take_profit_order.price
            select_order.binance_status = OrderBinanceStatus.FILLED
            session.commit()
        return take_profit_order

    return execute_sqlmodel_query_single(create_order)


# @task
def create_long_limit_order(
        symbol: str,
        price: Decimal,
        quantity: Decimal,
        leverage: int,
        webhook_id
) -> Order:
    print("create_long_limit_order:")

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

        select_order: Order = session.query(Order).filter(Order.binance_id == limit_order.binance_id).first()
        if not select_order:

            binance_position = get_exist_position(
                symbol=symbol,
                webhook_id=webhook_id,
                position_side=OrderPositionSide.LONG
            )
            if binance_position:
                limit_order.binance_position = binance_position

            session.add(limit_order)
            session.commit()
        else:
            logging.warning(f"Order already exists: {limit_order.binance_id}")
            select_order.status = OrderStatus.IN_PROGRESS
            select_order.price = limit_order.price
            select_order.binance_status = OrderBinanceStatus.FILLED
            session.commit()

        return limit_order

    return execute_sqlmodel_query_single(create_order)


# @task
def create_short_market_stop_order(
        symbol: str,
        price: Decimal,
        quantity: Decimal,
        leverage: int,
        webhook_id
) -> Order:
    # open short position
    print("create_short_market_stop_order:")

    def create_order(session):
        order = Order(
            position_side=OrderPositionSide.SHORT,
            side=OrderSide.SELL,
            type=OrderType.SHORT_MARKET_STOP_OPEN,
            symbol=symbol,
            price=price,
            quantity=quantity,
            leverage=leverage,
            webhook_id=webhook_id,
        )

        order.binance_id = create_order_binance(order)

        if not order.binance_id:
            order.type = OrderType.SHORT_MARKET
            order.binance_id = create_order_binance(order)

        order.status = OrderStatus.IN_PROGRESS

        pprint(order.model_dump())

        # session.add(order)
        # session.commit()
        return order

    return execute_sqlmodel_query_single(create_order)


# @task
def create_short_market_stop_loss_order(
        symbol: str,
        sl_short: float,
        leverage: int,
        webhook_id,
        position_short: BinancePosition,
        price_original: Decimal = None,
) -> Order:
    print("create_short_market_stop_loss_order:")

    def create_order(session):
        price_position = Decimal(position_short.entry_price) * (1 + Decimal(sl_short) / 100)
        quantity = abs(position_short.position_qty)
        print('price:', price_position)
        print('quantity:', quantity)

        order = Order(
            position_side=OrderPositionSide.SHORT,
            side=OrderSide.BUY,
            type=OrderType.SHORT_MARKET_STOP_LOSS,
            symbol=symbol,
            price=price_position,
            quantity=quantity,
            leverage=leverage,
            webhook_id=webhook_id,
        )

        order.binance_id = create_order_binance(order)

        if not order.binance_id:
            order.type = OrderType.SHORT_MARKET
            order.binance_id = create_order_binance(order)

        order.status = OrderStatus.IN_PROGRESS
        pprint(order.model_dump())

        # session.add(order)
        # session.commit()
        return order

    return execute_sqlmodel_query_single(create_order)


# @task
def create_long_trailing_stop_order(
        symbol: str,
        leverage: int,
        webhook_id,
        position_long: BinancePosition,
        trailing_2: Decimal
) -> Order:
    print("create_long_trailing_stop_order:")

    def create_order(session):
        cancel_in_progress_orders(symbol, webhook_id, OrderType.LONG_TAKE_PROFIT)
        cancel_in_progress_orders(symbol, webhook_id, OrderType.LONG_TRAILING_STOP_MARKET)

        # Рассчитываем цену активации трейлинга с использованием long_adjusted_break_even_price
        activation_price = position_long.activation_price
        trail_follow_price = Decimal(trailing_2 / 100)

        # Настройка параметров трейлинг-стоп ордера
        trailing_stop_order = Order(
            position_side=OrderPositionSide.LONG,
            side=OrderSide.SELL,
            type=OrderType.LONG_TRAILING_STOP_MARKET,  # Используем обновленный тип ордера
            symbol=symbol,
            quantity=position_long.position_qty,
            leverage=leverage,
            webhook_id=webhook_id,
            price=activation_price,  # Цена активации трейлинга
        )

        # Создание ордера на Binance
        trailing_stop_order.binance_id = create_order_binance(order=trailing_stop_order,
                                                              trail_follow_price=trail_follow_price)
        trailing_stop_order.status = OrderStatus.IN_PROGRESS

        # Привязка ордера к существующей позиции
        binance_position = get_exist_position(
            symbol=symbol,
            webhook_id=webhook_id,
            position_side=OrderPositionSide.LONG
        )
        if binance_position:
            trailing_stop_order.binance_position = binance_position

        pprint(trailing_stop_order.model_dump())

        # Сохранение ордера в базе данных
        select_order: Order = session.query(Order).filter(Order.binance_id == trailing_stop_order.binance_id).first()
        if not select_order:
            session.add(trailing_stop_order)
            session.commit()
        else:
            logging.warning(f"Order already exists: {trailing_stop_order.binance_id}")
            select_order.status = OrderStatus.IN_PROGRESS
            select_order.type = OrderType.LONG_TRAILING_STOP_MARKET  # Обновленный тип ордера
            select_order.price = activation_price
            # select_order.trail_amount = trail_follow_price
            # select_order.trail_step = trail_step
            select_order.binance_status = OrderBinanceStatus.FILLED
            session.commit()

        return trailing_stop_order

    return execute_sqlmodel_query_single(create_order)
