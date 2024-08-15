from decimal import Decimal
from datetime import datetime, timedelta

from prefect import task
from sqlalchemy.orm import joinedload
from sqlmodel import Session, select

from core.clients.db_sync import SessionLocal, execute_sqlmodel_query
from core.models.binance_position import BinancePosition, PositionStatus
from core.models.orders import Order, OrderStatus, OrderType, OrderPositionSide, OrderSide
from core.models.monitor import SymbolPosition


# @task #todo: почемуто считает ее ассинхронной
def save_position(
        position: SymbolPosition,
        position_side: OrderPositionSide,
        symbol: str,
        webhook_id: int,
        status: PositionStatus = PositionStatus.OPEN,
):
    with SessionLocal() as session:

        position_exist = get_exist_position(
            symbol=symbol,
            webhook_id=webhook_id,
            position_side=position_side
        )

        if position_side == OrderPositionSide.LONG:

            if position_exist:
                #     update existing position
                position_exist.activation_price = position.long_adjusted_break_even_price * (1 + position.trailing_1 / 100)
                position_exist.status = status
                position_exist.updated_at = datetime.utcnow()

                if status == PositionStatus.CLOSED or position.long_qty == 0:
                    position_exist.closed_at = datetime.utcnow()
                    position_exist.pnl = position.long_pnl

                elif status == PositionStatus.OPEN:
                    position_exist.pnl = 0
                else:
                    position_exist.position_qty = position.long_qty
                    position_exist.entry_price = position.long_entry
                    position_exist.entry_break_price = position.long_break_even_price

                position = position_exist

            else:

                position: BinancePosition = BinancePosition(
                    symbol=symbol,
                    position_side=OrderPositionSide.LONG,
                    position_qty=position.long_qty,
                    entry_price=position.long_entry,
                    entry_break_price=position.long_break_even_price,
                    pnl=position.long_pnl,
                    webhook_id=webhook_id,
                    status=status,
                    activation_price=position.long_adjusted_break_even_price * (1 + position.trailing_1 / 100),
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow()
                )

        elif position_side == OrderPositionSide.SHORT:

            if position_exist:
                #     update existing position
                position_exist.status = status
                position_exist.updated_at = datetime.utcnow()
                position_exist.activation_price = position.short_adjusted_break_even_price * (1 + position.trailing_1 / 100)

                if status == PositionStatus.CLOSED or position.short_qty == 0:
                    position_exist.closed_at = datetime.utcnow()
                    position_exist.pnl = position.short_pnl
                elif status == PositionStatus.OPEN:
                    position_exist.pnl = 0
                else:
                    position_exist.position_qty = position.short_qty
                    position_exist.entry_price = position.short_entry
                    position_exist.entry_break_price = position.short_break_even_price

                position = position_exist

            else:

                position: BinancePosition = BinancePosition(
                    symbol=symbol,
                    position_side=OrderPositionSide.SHORT,
                    position_qty=position.short_qty,
                    entry_price=position.short_entry,
                    entry_break_price=position.short_break_even_price,
                    pnl=position.short_pnl,
                    webhook_id=webhook_id,
                    activation_price=position.short_adjusted_break_even_price * (1 + position.trailing_1 / 100),
                    status=status,
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow()
                )

        session.merge(position)
        session.commit()
        return position


def get_exist_position(symbol: str, webhook_id: int = None, position_side: OrderPositionSide = None, check_closed=True) -> BinancePosition:
    """
    Load all orders with status IN_PROGRESS from the database.
    """

    def query_func(session):
        query = select(BinancePosition).where(
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
