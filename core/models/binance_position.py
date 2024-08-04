import enum
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional, Literal, List

from sqlmodel import SQLModel, Field, Relationship
from core.models.orders import OrderPositionSide, Order


class PositionStatus(enum.Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    UPDATED = "UPDATED"


class BinancePosition(SQLModel, table=True):
    id: int = Field(default=None, primary_key=True)
    webhook_id: Optional[int] = Field(default=None, foreign_key="webhook.id", index=True)
    symbol: str = Field(default=None, index=True)
    position_side: OrderPositionSide
    position_qty: Decimal = Field(default=0)
    entry_price: Decimal = Field(default=0)
    entry_break_price: Decimal = Field(default=0)
    status: PositionStatus = PositionStatus.OPEN

    pnl: float = Field(default=0)

    orders: List[Order] = Relationship(sa_relationship_kwargs={"back_populates": "binance_position"})

    created_at: datetime = Field(
        default_factory=datetime.now,
        nullable=False,
    )
    updated_at: datetime = Field(
        default_factory=datetime.now,
        nullable=False,
    )

    closed_at: Optional[datetime] = Field(default=None)
