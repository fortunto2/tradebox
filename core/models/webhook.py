import enum
from decimal import Decimal
from typing import Optional, Literal

from sqlalchemy.dialects.sqlite import JSON
from sqlmodel import SQLModel, Field


class WebHook(SQLModel, table=True):

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    side: str
    positionSide: str
    symbol: str
    open: JSON
    settings: JSON
    status: str = 'new'

