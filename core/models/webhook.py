import enum
from decimal import Decimal
from typing import Optional, Literal, Dict, List

from sqlmodel import SQLModel, Field, JSON, Relationship


class WebHook(SQLModel, table=True):

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    side: str
    positionSide: str
    symbol: str
    open: Optional[dict] = Field(nullable=True, sa_type=JSON)
    settings: Optional[dict] = Field(nullable=True, sa_type=JSON)
    status: str = 'new'

    orders: List["Order"] = Relationship(back_populates="webhook")
