from decimal import Decimal

from pydantic import BaseModel, Field


class AggregatedTradeEvent(BaseModel):
    event_type: str = Field(alias="e")
    event_time: int = Field(alias="E")
    aggregate_trade_id: int = Field(alias="a")
    symbol: str = Field(alias="s")
    price: Decimal = Field(alias="p")
    quantity: Decimal = Field(alias="q")
    first_trade_id: int = Field(alias="f")
    last_trade_id: int = Field(alias="l")
    trade_time: int = Field(alias="T")
    is_buyer_maker: bool = Field(alias="m")
