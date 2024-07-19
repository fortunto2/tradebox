import enum
from datetime import datetime, timedelta
from decimal import Decimal

from sqlmodel import SQLModel, Field
from core.models.orders import OrderPositionSide


class BinancePosition(SQLModel, table=True):
    symbol: str
    position_side: OrderPositionSide
    position_qty: Decimal
    entry_price: Decimal
    pnl: Decimal = Field(default=0)

    created_at: datetime = Field(
        default_factory=datetime.now,
        nullable=False,
    )
