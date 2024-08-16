import logging
from decimal import Decimal
import sys
from pprint import pprint

from binance.error import ClientError
from prefect import task
from sqlalchemy.exc import IntegrityError

from core.models.binance_position import PositionStatus
from core.models.monitor import SymbolPosition
from core.schemas.position import LongPosition, ShortPosition
from core.schemas.webhook import WebhookPayload
from core.views.handle_positions import get_exist_position, save_position
from flows.tasks.binance_futures import create_order_binance, check_position, cancel_order_binance, get_order_id
from core.models.orders import Order, OrderPositionSide, OrderType, OrderSide, OrderStatus, OrderBinanceStatus
from core.views.handle_orders import db_get_all_order
from core.clients.db_sync import execute_sqlmodel_query_single

sys.path.append('../../core')
sys.path.append('')


@task
def create_long_market_order(
        symbol: str,
        quantity: Decimal,
        leverage: int,
        webhook_id,
        side: OrderSide = OrderSide.BUY,
        payload: WebhookPayload = None
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

        position_long, _ = check_position(symbol=symbol)
        position_long: LongPosition

        if position_long:
            market_order.price = position_long.entryPrice
            market_order.status = OrderStatus.FILLED

        market_order.binance_status = OrderBinanceStatus.FILLED

        pprint(market_order.model_dump())

        select_order: Order = session.query(Order).filter(Order.binance_id == market_order.binance_id).first()
        if not select_order:
            session.add(market_order)
            session.commit()
        else:
            logging.warning(f"Order already exists: {market_order.binance_id}")
            select_order.status = OrderStatus.FILLED
            select_order.price = market_order.price
            select_order.binance_status = OrderBinanceStatus.FILLED
            session.commit()

        # ----position open

        position = SymbolPosition(
            symbol=symbol,
            long_qty=market_order.quantity,
            long_entry=market_order.price,
            long_break_even_price=position_long.breakEvenPrice,
            long_pnl=0,
            trailing_1=payload.settings.trail_1,
            trailing_2=payload.settings.trail_2,
            webhook_id=webhook_id,
        )
        position.calculate_pnl_long(market_order.price)
        position.calculate_long_adjusted_break_even_price()

        if side == OrderSide.BUY:
            status = PositionStatus.OPEN
        else:
            status = PositionStatus.CLOSED

        save_position(
            position=position,
            position_side=OrderPositionSide.LONG,
            symbol=symbol,
            webhook_id=webhook_id,
            status=status
        )

        return market_order

    return execute_sqlmodel_query_single(create_order)


@task
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
        market_order.binance_id = order_binance_id

        if position_short:
            market_order.price = position_short.entryPrice
            market_order.status = OrderStatus.FILLED

        market_order.binance_status = OrderBinanceStatus.FILLED
        select_order: Order = session.query(Order).filter(Order.binance_id == market_order.binance_id).first()
        if not select_order:
            session.add(market_order)
            session.commit()
        else:
            logging.warning(f"Order already exists: {market_order.binance_id}")
            select_order.status = OrderStatus.FILLED
            select_order.price = market_order.price
            select_order.binance_status = OrderBinanceStatus.FILLED
            session.commit()

        return market_order

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
        position: SymbolPosition = None
) -> Order:
    print("Take profit order:")

    def create_order(session):
        cancel_in_progress_orders(symbol, webhook_id, OrderType.LONG_TAKE_PROFIT)

        if not position:
            position_long, _ = check_position(symbol=symbol)
            position_long: LongPosition

            long_entry = position_long.entryPrice
            long_qty = position_long.positionAmt
        else:
            long_entry = position.long_adjusted_break_even_price
            long_qty = position.long_qty

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
        take_profit_order.status = OrderStatus.IN_PROGRESS

        binance_position = get_exist_position(
            symbol=symbol,
            webhook_id=webhook_id,
            position_side=OrderPositionSide.LONG
        )
        if binance_position:
            take_profit_order.binance_position = binance_position

        pprint(take_profit_order.model_dump())
        select_order: Order = session.query(Order).filter(Order.binance_id == take_profit_order.binance_id).first()
        if not select_order:
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


@task
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

        select_order: Order = session.query(Order).filter(Order.binance_id == limit_order.binance_id).first()
        if not select_order:
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


@task
def create_short_market_stop_order(
        symbol: str,
        price: Decimal,
        quantity: Decimal,
        leverage: int,
        webhook_id
) -> Order:
    # open short position
    print("Creating SHORT STOP order:")

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


@task
def create_short_market_stop_loss_order(
        symbol: str,
        sl_short: float,
        leverage: int,
        webhook_id,
        position: SymbolPosition,
        price_original: Decimal = None,
) -> Order:
    print("SHORT-BUY:")

    def create_order(session):
        price_position = Decimal(position.short_entry) * (1 + Decimal(sl_short) / 100)
        quantity = abs(position.short_qty)
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


@task
def create_long_trailing_stop_order(
        symbol: str,
        leverage: int,
        webhook_id,
        position: SymbolPosition
) -> Order:
    print("Creating LONG TRAILING STOP order with custom parameters:")

    def create_order(session):
        cancel_in_progress_orders(symbol, webhook_id, OrderType.LONG_TAKE_PROFIT)
        cancel_in_progress_orders(symbol, webhook_id, OrderType.LONG_TRAILING_STOP_MARKET)

        # Рассчитываем цену активации трейлинга с использованием long_adjusted_break_even_price
        activation_price = position.long_adjusted_break_even_price * (1 + position.trailing_1 / 100)
        trail_follow_price = Decimal(position.trailing_2 / 100)

        # Настройка параметров трейлинг-стоп ордера
        trailing_stop_order = Order(
            position_side=OrderPositionSide.LONG,
            side=OrderSide.SELL,
            type=OrderType.LONG_TRAILING_STOP_MARKET,  # Используем обновленный тип ордера
            symbol=symbol,
            quantity=position.long_qty,
            leverage=leverage,
            webhook_id=webhook_id,
            price=activation_price,  # Цена активации трейлинга
            # trail_amount=trail_follow_price,  # Процент следования за ценой #callbackRate
            # trail_step=trail_step  # Шаг перемещения ордера
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
