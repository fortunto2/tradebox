from datetime import datetime
from decimal import Decimal
from typing import List, Union, Literal, Optional

from pydantic import BaseModel, validator, field_validator

from core.models.orders import OrderSide, OrderPositionSide


# Define Pydantic models for webhook validation
class OpenOrder(BaseModel):
    enabled: bool
    amountType: str
    amount: Decimal
    leverage: int


class Settings(BaseModel):
    deposit: float
    time_allert: Optional[datetime] = None
    extramarg: float
    tp: Decimal
    trail_1: float
    trail_2: float
    offset_short: float
    offset_pluse: float
    sl_short: float
    grid_long: Union[str, List[float]]
    mg_long: Union[str, List[float]]
    trail_step: float
    order_quan: int
    sens: Optional[int]
    time_frame: Optional[str] = None

    @field_validator('grid_long', 'mg_long', mode='before')
    def split_string_to_list(cls, v):
        if isinstance(v, str):
            return [Decimal(item) for item in v.split('|')]
        return v


class WebhookPayload(BaseModel):
    name: str
    side: OrderSide
    positionSide: OrderPositionSide
    symbol: str
    open: OpenOrder
    settings: Settings

    @field_validator('side', mode='before')
    def validate_side(cls, v):
        if isinstance(v, str):
            v = v.upper()
        if v in OrderSide.__members__:
            return OrderSide[v]
        elif v in OrderSide:
            return v
        raise ValueError('Invalid value for side')

    @field_validator('positionSide', mode='before')
    def validate_position_side(cls, v):
        if isinstance(v, str):
            v = v.upper()
        if v in OrderPositionSide.__members__:
            return OrderPositionSide[v]
        elif v in OrderPositionSide:
            return v
        raise ValueError('Invalid value for positionSide')
