import logging
from decimal import Decimal
from typing import List, Dict
from pydantic import BaseModel, Field

from core.models.webhook import WebHook


class SymbolPositionState(BaseModel):
    """
    Состояние различных переменных кешируем по символу для работы в вебсокетах без базы
    """
    long_trailing_price: Decimal = Field(default_factory=lambda: Decimal(0))
    short_trailing_price: Decimal = Field(default_factory=lambda: Decimal(0))


class TradeMonitorBase:

    def __init__(self, symbols: List[str]):
        self.symbols = symbols

    def on_message(self, message):
        pass


if __name__ == '__main__':
    # SymbolPosition
    symbol_position = SymbolPositionState(long_trailing_price=Decimal(0))
