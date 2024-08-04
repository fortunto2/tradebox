import logging
from decimal import Decimal
import sys
from pprint import pprint

from binance.error import ClientError
from prefect import task
from sqlalchemy.exc import IntegrityError

from core.models.monitor import SymbolPosition
from core.schemas.position import LongPosition, ShortPosition
from core.views.handle_positions import get_exist_position
from flows.tasks.binance_futures import create_order_binance, check_position, cancel_order_binance
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

        position_long, _ = check_position(symbol=symbol)
        position_long: LongPosition

        if position_long:
            market_order.price = position_long.entryPrice
            market_order.status = OrderStatus.FILLED

        market_order.binance_status = OrderBinanceStatus.FILLED

        pprint(market_order.model_dump())
        try:
            session.add(market_order)
            session.commit()
        except IntegrityError as e:
            print(e)
            logging.warning(f"Error creating order: {e}")
        #     select and update
            select_order = session.query(Order).filter(Order.binance_id == market_order.binance_id).first()
            select_order.status = OrderStatus.FILLED
            session.commit()

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
        session.add(market_order)
        session.commit()
        return market_order


    return execute_sqlmodel_query_single(create_order)


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
        orders = db_get_all_order(webhook_id, OrderStatus.IN_PROGRESS, OrderType.LONG_TAKE_PROFIT)
        for order in orders:
            try:
                result = cancel_order_binance(symbol, order.binance_id)
                if result['status'] == 'CANCELED':
                    order.status = OrderStatus.CANCELED
            except Exception as e:
                print(e)
                logging.error(f"Error canceling order: {e}")

        if not position:
            position_long, _ = check_position(symbol=symbol)
            position_long: LongPosition

            long_entry = position_long.entryPrice
            long_qty = position_long.positionAmt
        else:
            long_entry = position.long_entry
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
        session.add(take_profit_order)
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

        session.add(limit_order)
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

        try:
            order.binance_id = create_order_binance(order)
        except Exception as e:
            print(e)
        order.status = OrderStatus.IN_PROGRESS
        pprint(order.model_dump())

        # session.add(order)
        # session.commit()
        return order

    return execute_sqlmodel_query_single(create_order)
