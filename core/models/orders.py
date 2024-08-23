import enum
from datetime import datetime
from decimal import Decimal
from typing import Optional, Literal

from sqlmodel import Index
from sqlmodel import SQLModel, Field, Relationship

from core.models.base import BaseTable


# from core.models.webhook import WebHook


class OrderBinanceStatus(enum.Enum):
    NEW = "NEW"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    EXPIRED = "EXPIRED"
    EXPIRED_IN_MATCH = "EXPIRED_IN_MATCH"


class OrderStatus(enum.Enum):
    NEW = "NEW"
    IN_PROGRESS = "IN_PROGRESS"
    FILLED = "FILLED"
    CANCELED = "CANCELED"


class OrderPositionSide(enum.Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class OrderSide(enum.Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(enum.Enum):
    """
    Type	Additional mandatory parameters
    LIMIT	timeInForce, quantity, price
    MARKET	quantity
    STOP/TAKE_PROFIT	quantity, price, stopPrice
    STOP_MARKET/TAKE_PROFIT_MARKET	stopPrice
    TRAILING_STOP_MARKET	quantity,callbackRate
    """

    LONG_LIMIT = "LONG_LIMIT"
    LONG_MARKET = "LONG_MARKET"
    SHORT_MARKET = "SHORT_MARKET"
    LONG_TAKE_PROFIT = "LONG_TAKE_PROFIT"
    # our custom
    SHORT_LIMIT = "SHORT_LIMIT"
    # SHORT_STOP_LOSS = "SHORT_STOP_LOSS" # depricated, switch to SHORT_MARKET_STOP_LOSS
    SHORT_MARKET_STOP_LOSS = "SHORT_MARKET_STOP_LOSS"
    SHORT_MARKET_STOP_OPEN = "SHORT_MARKET_STOP_OPEN"
    LONG_TRAILING_STOP_MARKET = "LONG_TRAILING_STOP_MARKET"


class Order(BaseTable, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    webhook_id: Optional[int] = Field(default=None, foreign_key="webhook.id", index=True)
    webhook: "WebHook" = Relationship(back_populates="orders")
    binance_id: Optional[str] = Field(default=None, index=True, unique=True)
    symbol: str = Field(default=None, foreign_key="binancesymbol.symbol", index=True)
    symbol_info: "BinanceSymbol" = Relationship(back_populates="orders")

    side: OrderSide = OrderSide.BUY
    position_side: OrderPositionSide
    price: Optional[Decimal] = None
    stop_price: Optional[Decimal] = None  # for Limit orders
    quantity: Decimal
    leverage: Optional[int] = None
    type: OrderType
    status: Optional[OrderStatus] = OrderStatus.NEW
    binance_status: Optional[OrderBinanceStatus] = None
    binance_position_id: Optional[int] = Field(default=None, foreign_key="binanceposition.id", index=True)
    binance_position: "BinancePosition" = Relationship(back_populates="orders")

    commission_asset: Optional[str] = None
    commission: Optional[Decimal] = None

    __table_args__ = (
        Index("idx_order_uniq_position", "binance_position_id", "type", "status"),
    )
