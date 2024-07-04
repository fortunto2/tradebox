from pydantic import BaseModel, Field
from typing import List, Literal
from decimal import Decimal


class Balance(BaseModel):
    asset: str = Field(alias="a")
    wallet_balance: Decimal = Field(alias="wb")
    cross_wallet_balance: Decimal = Field(alias="cw")
    balance_change: Decimal = Field(alias="bc")


class Position(BaseModel):
    symbol: str = Field(alias="s")
    position_amount: Decimal = Field(alias="pa")
    entry_price: Decimal = Field(alias="ep")
    breakeven_price: Decimal = Field(alias="bep")
    accumulated_realized: Decimal = Field(alias="cr")
    unrealized_pnl: Decimal = Field(alias="up")
    margin_type: Literal["isolated", "cross"] = Field(alias="mt")
    isolated_wallet: Decimal = Field(alias="iw")
    position_side: Literal["BOTH", "LONG", "SHORT"] = Field(alias="ps")

