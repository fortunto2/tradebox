from datetime import datetime
from decimal import Decimal
from typing import List, Union, Literal, Optional

from pydantic import BaseModel, validator, field_validator


# Define Pydantic models for webhook validation
class OpenOrder(BaseModel):
    enabled: bool
    amountType: str
    amount: Decimal
    leverage: int


class Settings(BaseModel):
    deposit: float
    time_allert: datetime
    extramarg: float
    tp: float
    trail_1: float
    trail_2: float
    offset_short: float
    sl_short: float
    grid_long: Union[str, List[float]]
    mg_long: Union[str, List[float]]
    trail_step: float
    order_quan: int
    sens: Optional[int]
    time_frame: Optional[str]

    @field_validator('grid_long', 'mg_long', mode='before')
    def split_string_to_list(cls, v):
        if isinstance(v, str):
            return [Decimal(item) for item in v.split('|')]
        return v


class WebhookPayload(BaseModel):
    name: str
    side: Literal['BUY', 'SELL']
    positionSide: str
    symbol: str
    open: OpenOrder
    settings: Settings

    @field_validator('side', mode='before')
    def select_side(cls, v):
        if v.lower() == 'buy':
            return 'BUY'
        elif v.lower() == 'sell':
            return 'SELL'
        else:
            return v.upper()
