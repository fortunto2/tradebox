from pydantic import BaseModel, Field
from typing import List, Literal
from decimal import Decimal

from core.schemas.events.base import Balance, Position


class UpdateData(BaseModel):
    event_reason_type: str = Field(alias="m")
    balances: List[Balance] = Field(default=[], alias="B")
    positions: List[Position] = Field(default=[], alias="P")


class AccountUpdateEvent(BaseModel):
    event_type: str = Field(alias="e")
    event_time: int = Field(alias="E")
    transaction_time: int = Field(alias="T")
    update_data: UpdateData = Field(alias="a")
