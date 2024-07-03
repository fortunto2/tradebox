# {
#     "clientOrderId": "myOrder1",
#     "cumQty": "0",
#     "cumQuote": "0",
#     "executedQty": "0",
#     "orderId": 283194212,
#     "origQty": "11",
#     "origType": "TRAILING_STOP_MARKET",
#     "price": "0",
#     "reduceOnly": false,
#     "side": "BUY",
#     "positionSide": "SHORT",
#     "status": "CANCELED",
#     "stopPrice": "9300",                // please ignore when order type is TRAILING_STOP_MARKET
#     "closePosition": false,   // if Close-All
#     "symbol": "BTCUSDT",
#     "timeInForce": "GTC",
#     "type": "TRAILING_STOP_MARKET",
#     "activatePrice": "9020",            // activation price, only return with TRAILING_STOP_MARKET order
#     "priceRate": "0.3",                 // callback rate, only return with TRAILING_STOP_MARKET order
#     "updateTime": 1571110484038,
#     "workingType": "CONTRACT_PRICE",
#     "priceProtect": false,            // if conditional order trigger is protected
#     "priceMatch": "NONE",              //price match mode
#     "selfTradePreventionMode": "NONE", //self trading preventation mode
#     "goodTillDate": 0                  //order pre-set auot cancel time for TIF GTD order
# }
from pydantic import BaseModel, Field, validator
from datetime import datetime
from decimal import Decimal
from typing import Literal, Optional
from core.models.orders import OrderPositionSide, OrderSide  # Assuming you have these enums defined

class BinanceOrder(BaseModel):
    clientOrderId: str
    cumQty: Decimal
    cumQuote: Decimal
    executedQty: Decimal
    orderId: int
    origQty: Decimal
    origType: Literal["TRAILING_STOP_MARKET"]  # As example, add other types as necessary
    price: Decimal
    reduceOnly: bool
    side: OrderSide
    positionSide: OrderPositionSide
    status: Literal['FILLED', 'CANCELED', 'REJECTED']
    stopPrice: Decimal
    closePosition: bool
    symbol: str
    timeInForce: Literal['GTC']  # Add other time in force options as necessary
    type: Literal["TRAILING_STOP_MARKET"]  # Add other order types as necessary
    activatePrice: Optional[Decimal] = None
    priceRate: Optional[Decimal] = None
    updateTime: datetime
    workingType: Literal['CONTRACT_PRICE', 'MARK_PRICE']  # Example values, add more if needed
    priceProtect: bool
    priceMatch: Literal['NONE']  # Add other values as needed
    selfTradePreventionMode: Literal['NONE']  # Add other modes if they exist
    goodTillDate: Optional[int] = None

    @validator('updateTime', pre=True)
    def convert_timestamp(cls, v):
        return datetime.fromtimestamp(v / 1000.0)  # Convert milliseconds to seconds

    class Config:
        use_enum_values = True  # Ensures that enums are serialized to their value


# Additional Enums for demonstration, ensure these match your actual usage or replace with actual enum definitions
from enum import Enum


class OrderSide(Enum):
    BUY = 'BUY'
    SELL = 'SELL'


class OrderPositionSide(Enum):
    LONG = 'LONG'
    SHORT = 'SHORT'
