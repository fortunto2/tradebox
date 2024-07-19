from decimal import Decimal
from datetime import datetime, timedelta
from sqlmodel import Session, select

from core.clients.db_sync import SessionLocal
from core.models.binance_position import BinancePosition


def save_position(symbol: str, position_side: str, position_qty: Decimal, entry_price: Decimal, pnl: Decimal):
    with SessionLocal() as session:
        position = BinancePosition(
            symbol=symbol,
            position_side=position_side,
            position_qty=position_qty,
            entry_price=entry_price,
            pnl=pnl,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        session.add(position)
        session.commit()
        return position


def get_positions(symbol: str = None):
    with SessionLocal() as session:
        if symbol:
            query = select(BinancePosition).where(BinancePosition.symbol == symbol)
        else:
            query = select(BinancePosition)
        result = session.exec(query)
        return result.all()


def delete_old_positions():
    with SessionLocal() as session:
        one_week_ago = datetime.utcnow() - timedelta(weeks=1)
        query = select(BinancePosition).where(BinancePosition.created_at < one_week_ago)
        old_positions = session.exec(query).all()
        for position in old_positions:
            session.delete(position)
        session.commit()
        return old_positions
