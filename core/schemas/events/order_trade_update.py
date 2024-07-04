import enum

from pydantic import BaseModel, Field
from typing import List, Literal, Optional, Union
from decimal import Decimal

from core.schemas.events.base import Balance, Position

#
# {
#   "e":"ORDER_TRADE_UPDATE",     // Event Type
#   "E":1568879465651,            // Event Time
#   "T":1568879465650,            // Transaction Time
#   "o":{
#     "s":"BTCUSDT",              // Symbol
#     "c":"TEST",                 // Client Order Id
#       // special client order id:
#       // starts with "autoclose-": liquidation order
#       // "adl_autoclose": ADL auto close order
#       // "settlement_autoclose-": settlement order for delisting or delivery
#     "S":"SELL",                 // Side
#     "o":"TRAILING_STOP_MARKET", // Order Type
#     "f":"GTC",                  // Time in Force
#     "q":"0.001",                // Original Quantity
#     "p":"0",                    // Original Price
#     "ap":"0",                   // Average Price
#     "sp":"7103.04",             // Stop Price. Please ignore with TRAILING_STOP_MARKET order
#     "x":"NEW",                  // Execution Type
#     "X":"NEW",                  // Order Status
#     "i":8886774,                // Order Id
#     "l":"0",                    // Order Last Filled Quantity
#     "z":"0",                    // Order Filled Accumulated Quantity
#     "L":"0",                    // Last Filled Price
#     "N":"USDT",                 // Commission Asset, will not push if no commission
#     "n":"0",                    // Commission, will not push if no commission
#     "T":1568879465650,          // Order Trade Time
#     "t":0,                      // Trade Id
#     "b":"0",                    // Bids Notional
#     "a":"9.91",                 // Ask Notional
#     "m":false,                  // Is this trade the maker side?
#     "R":false,                  // Is this reduce only
#     "wt":"CONTRACT_PRICE",      // Stop Price Working Type
#     "ot":"TRAILING_STOP_MARKET",// Original Order Type
#     "ps":"LONG",                // Position Side
#     "cp":false,                 // If Close-All, pushed with conditional order
#     "AP":"7476.89",             // Activation Price, only puhed with TRAILING_STOP_MARKET order
#     "cr":"5.0",                 // Callback Rate, only puhed with TRAILING_STOP_MARKET order
#     "pP": false,                // If price protection is turned on
#     "si": 0,                    // ignore
#     "ss": 0,                    // ignore
#     "rp":"0",                   // Realized Profit of the trade
#     "V":"EXPIRE_TAKER",         // STP mode
#     "pm":"OPPONENT",            // Price match mode
#     "gtd":0                     // TIF GTD order auto cancel time
#   }
# }

class OrderType(enum.Enum):
    LIMIT = "LIMIT"
    MARKET = "MARKET"
    TAKE_PROFIT = "TAKE_PROFIT"
    STOP = "STOP"
    STOP_MARKET = "STOP_MARKET"
    TRAILING_STOP_MARKET = "TRAILING_STOP_MARKET"
    TAKE_PROFIT_MARKET = "TAKE_PROFIT_MARKET"


class Order(BaseModel):
    symbol: str = Field(alias="s")
    client_order_id: str = Field(alias="c")
    side: Literal["SELL", "BUY"] = Field(alias="S")
    order_type: str = Field(alias="o")
    time_in_force: Literal["GTC"] = Field(alias="f")
    original_quantity: Decimal = Field(alias="q")
    original_price: Decimal = Field(alias="p")
    average_price: Decimal = Field(alias="ap")
    stop_price: Decimal = Field(alias="sp")
    execution_type: str = Field(alias="x")
    order_status: Union[Literal["NEW", "FILLED", "REJECTED", "CANCELLED"], str] = Field(alias="X")
    order_id: int = Field(alias="i")
    last_filled_quantity: Decimal = Field(alias="l")
    filled_accumulated_quantity: Decimal = Field(alias="z")
    last_filled_price: Decimal = Field(alias="L")
    commission_asset: Optional[str] = Field(alias="N", default=None)
    commission: Optional[Decimal] = Field(alias="n", default=None)
    order_trade_time: int = Field(alias="T")
    trade_id: int = Field(alias="t")
    bids_notional: Decimal = Field(alias="b")
    asks_notional: Decimal = Field(alias="a")
    is_maker: bool = Field(alias="m")
    reduce_only: bool = Field(alias="R")
    stop_price_working_type: str = Field(alias="wt")
    original_order_type: str = Field(alias="ot")
    position_side: Literal["LONG", "SHORT", "BOTH"] = Field(alias="ps")
    close_all: bool = Field(alias="cp")
    activation_price: Optional[Decimal] = Field(alias="AP", default=None)
    callback_rate: Optional[Decimal] = Field(alias="cr", default=None)
    price_protection: bool = Field(alias="pP")
    realized_profit: Decimal = Field(alias="rp")


class OrderTradeUpdateEvent(BaseModel):
    "https://binance-docs.github.io/apidocs/futures/en/#event-order-update"
    event_type: str = Field(alias="e")
    event_time: int = Field(alias="E")
    transaction_time: int = Field(alias="T")
    order: Order = Field(alias="o")
