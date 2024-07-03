from pydantic import BaseModel, Field, validator
from datetime import datetime
from decimal import Decimal
from typing import Literal, Optional

from core.models.orders import OrderPositionSide


class BasePosition(BaseModel):
    """
    Result For Hedge position mode:

    [
        {
            "symbol": "BTCUSDT",
            "positionAmt": "0.001",
            "entryPrice": "22185.2",  - цена входа
            "breakEvenPrice": "0.0",  - цена без убытка
            "markPrice": "21123.05052574", - цена по рынку, всегда есть даже без ордеров
            "unRealizedProfit": "-1.06214947",
            "liquidationPrice": "19731.45529116",
            "leverage": "4",
            "maxNotionalValue": "100000000",
            "marginType": "cross",
            "isolatedMargin": "0.00000000",
            "isAutoAddMargin": "false",
            "positionSide": "LONG",
            "notional": "21.12305052",
            "isolatedWallet": "0",
            "updateTime": 1655217461579
        },
        {
            "symbol": "BTCUSDT",
            "positionAmt": "0.000",
            "entryPrice": "0.0",
            "breakEvenPrice": "0.0",
            "markPrice": "21123.05052574",
            "unRealizedProfit": "0.00000000",
            "liquidationPrice": "0",
            "leverage": "4",
            "maxNotionalValue": "100000000",
            "marginType": "cross",
            "isolatedMargin": "0.00000000",
            "isAutoAddMargin": "false",
            "positionSide": "SHORT",
            "notional": "0",
            "isolatedWallet": "0",
            "updateTime": 0
        }
    ]
    """

    symbol: str
    positionAmt: Decimal
    entryPrice: Decimal = Field(description="цена входа")
    breakEvenPrice: Decimal = Field(description="цена без убытка")
    markPrice: Decimal = Field(description="цена по рынку, всегда есть даже без ордеров")
    unRealizedProfit: Decimal
    liquidationPrice: Decimal
    leverage: int
    maxNotionalValue: Decimal
    marginType: Literal['cross', 'isolated']
    isolatedMargin: Decimal
    isAutoAddMargin: bool
    positionSide: OrderPositionSide  # Используем перечисление из вашего кода
    notional: Decimal
    isolatedWallet: Decimal
    updateTime: Optional[datetime] = None


class LongPosition(BasePosition):
    positionSide: Literal['LONG']


class ShortPosition(BasePosition):
    positionSide: Literal['SHORT']
