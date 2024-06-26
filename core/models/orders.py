import enum
from decimal import Decimal
from typing import Optional, Literal

from sqlmodel import SQLModel, Field

from core.models.base import BaseTable


class OrderStatus(enum.Enum):
    NEW = "NEW"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    EXPIRED = "EXPIRED"
    EXPIRED_IN_MATCH = "EXPIRED_IN_MATCH"


class PositionSide(enum.Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class Order(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    symbol: str
    side: str
    price: Decimal
    quantity: Decimal
    leverage: int
    position_side: PositionSide
    status: Optional[OrderStatus] = None
