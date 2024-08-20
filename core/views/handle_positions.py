from decimal import Decimal
from datetime import datetime, timedelta

from sqlalchemy.orm import joinedload
from sqlmodel import Session, select

from core.clients.db_sync import SessionLocal, execute_sqlmodel_query
from core.models.binance_position import BinancePosition, PositionStatus
from core.models.binance_symbol import BinanceSymbol
from core.models.orders import OrderPositionSide
from core.views.handle_orders import get_webhook_last


# @task #todo: почемуто считает ее ассинхронной
def update_position_task(
        position: BinancePosition
):
    with SessionLocal() as session:

        trailing_1 = Decimal(position.webhook.settings.get('trail_1'))
        activation_price = position.calculate_adjusted_break_even_price() * (1 + trailing_1 / 100)
        position.activation_price = position.symbol_info.adjust_price(activation_price)

        session.merge(position)
        session.commit()
        return position


def close_position_task(
        position: BinancePosition,
        pnl: Decimal = None,
):
    with SessionLocal() as session:

        position.updated_at = datetime.utcnow()
        position.closed_at = datetime.utcnow()
        position.status = PositionStatus.CLOSED
        if pnl:
            # position.pnl = position.calculate_pnl()
            position.pnl = pnl

        session.merge(position)
        session.commit()
        return position


# @task
def open_position_task(
        symbol: str,
        position_qty: Decimal,
        position_side: OrderPositionSide,
        entry_price: Decimal,
        entry_break_price: Decimal,
        webhook_id: int = None,
        activation_price: Decimal = None,
        trailing_1: Decimal = None,
):
    with SessionLocal() as session:

        position: BinancePosition = get_exist_position(
            symbol=symbol,
            position_side=position_side,
        )

        if position:
            return position

        symbol_info = session.query(BinanceSymbol).filter_by(symbol=symbol).first()

        if not symbol_info:
            raise ValueError(f"Symbol {symbol} not found in BinanceSymbol table.")

        webhook = get_webhook_last(symbol)
        if not webhook_id:
            webhook_id = webhook.id

        position: BinancePosition = BinancePosition(
            symbol=symbol,
            symbol_info=symbol_info,
            position_side=position_side,
            position_qty=position_qty,
            entry_price=entry_price,
            entry_break_price=entry_break_price,
            webhook_id=webhook_id,
            activation_price=activation_price,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            status=PositionStatus.OPEN
        )

        session.add(position)
        session.commit()

        if not trailing_1:
            if position.webhook:
                trailing_1 = Decimal(position.webhook.settings.get('trail_1'))
            elif webhook:
                trailing_1 = Decimal(webhook.settings.get('trail_1'))

        if not activation_price and trailing_1:
            activation_price = position.calculate_adjusted_break_even_price() * (1 + trailing_1 / 100)
            position.activation_price = position.symbol_info.adjust_price(activation_price)

        position_id = position.id
        session.commit()

    return position_id


def get_exist_position(symbol: str, webhook_id: int = None, position_side: OrderPositionSide = None, check_closed=True) -> BinancePosition:
    """
    Load all orders with status IN_PROGRESS from the database.
    """
    if not webhook_id:
        # защита, чтоб если позицию в базе не закрыли предыдущую, не брал не свой вебхук
        webhook = get_webhook_last(symbol)
        if webhook:
            webhook_id = webhook.id
        else:
            return None

    def query_func(session):
        query = select(BinancePosition).options(
            joinedload(BinancePosition.webhook),
            joinedload(BinancePosition.symbol_info)
        ).where(
            BinancePosition.symbol == symbol
        ).order_by(BinancePosition.id.desc())

        if position_side:
            query = query.where(BinancePosition.position_side == position_side)
        if webhook_id:
            query = query.where(BinancePosition.webhook_id == webhook_id)
        if check_closed:
            query = query.where(BinancePosition.status != PositionStatus.CLOSED)

        result = session.exec(query)
        return result.first()

    return execute_sqlmodel_query(query_func)


def delete_old_positions():
    with SessionLocal() as session:
        one_week_ago = datetime.utcnow() - timedelta(weeks=1)
        query = select(BinancePosition).where(BinancePosition.created_at < one_week_ago)
        old_positions = session.exec(query).all()
        for position in old_positions:
            session.delete(position)
        session.commit()
        return old_positions
