from decimal import Decimal
from typing import List, Dict

from pydantic import BaseModel, Field


class SymbolPosition(BaseModel):
    long_qty: Decimal = Field(default_factory=lambda: Decimal(0))
    long_entry: Decimal = Field(default_factory=lambda: Decimal(0))
    short_qty: Decimal = Field(default_factory=lambda: Decimal(0))
    short_entry: Decimal = Field(default_factory=lambda: Decimal(0))
    long_pnl: Decimal = Field(default_factory=lambda: Decimal(0))
    short_pnl: Decimal = Field(default_factory=lambda: Decimal(0))


class TradeMonitorBase:

    def __init__(self, symbols: List[str]):
        self.symbols = symbols
        self.positions: Dict[str, SymbolPosition] = {symbol: SymbolPosition() for symbol in symbols}

    def on_message(self, message):
        pass
