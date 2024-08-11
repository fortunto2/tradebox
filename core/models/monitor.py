import logging
from decimal import Decimal
from typing import List, Dict

from pydantic import BaseModel, Field


class SymbolPosition(BaseModel):
    long_qty: Decimal = Field(default_factory=lambda: Decimal(0))
    long_entry: Decimal = Field(default_factory=lambda: Decimal(0)) # position_price
    long_break_even_price: Decimal = Field(default_factory=lambda: Decimal(0))
    long_adjusted_break_even_price: Decimal = Field(default_factory=lambda: Decimal(0))

    short_qty: Decimal = Field(default_factory=lambda: Decimal(0))
    short_entry: Decimal = Field(default_factory=lambda: Decimal(0)) # position_price
    short_break_even_price: Decimal = Field(default_factory=lambda: Decimal(0))
    short_adjusted_break_even_price: Decimal = Field(default_factory=lambda: Decimal(0))

    long_pnl: Decimal = Field(default_factory=lambda: Decimal(0))
    short_pnl: Decimal = Field(default_factory=lambda: Decimal(0))

    trailing_1: Decimal = Field(default_factory=lambda: Decimal(0))
    trailing_2: Decimal = Field(default_factory=lambda: Decimal(0))

    price_precision: int = 6

    def calculate_long_adjusted_break_even_price(self):
        if self.long_break_even_price is not None and self.long_entry is not None:
            # Long position: break_even_price > position_price
            percentage_difference = ((self.long_break_even_price - self.long_entry) / self.long_entry) * 100

            adjusted_percentage = percentage_difference * 2

            self.long_adjusted_break_even_price = Decimal(round(
                self.long_break_even_price + (self.long_entry * (adjusted_percentage / 100)),
                self.price_precision
            ))
            # Вывод процентного изменения и новой цены безубытка
            logging.debug(f"long adjusted_percentage: {round(adjusted_percentage, 2)}%, long new_break_even_price: {self.long_adjusted_break_even_price}")

            return self.long_adjusted_break_even_price

    def calculate_short_adjusted_break_even_price(self):
        if self.short_break_even_price is not None and self.short_entry is not None:
            # Long position: break_even_price > position_price
            percentage_difference = ((self.short_entry - self.short_break_even_price) / self.short_entry) * 100

            adjusted_percentage = percentage_difference * 2

            self.short_adjusted_break_even_price = Decimal(round(
                self.short_break_even_price - (self.short_entry * (adjusted_percentage / 100)),
                self.price_precision
            ))
            # Вывод процентного изменения и новой цены безубытка
            logging.debug(f"short adjusted_percentage: {round(adjusted_percentage, 2)}%, short new_break_even_price: {self.short_adjusted_break_even_price}")

            return self.short_adjusted_break_even_price

    def calculate_pnl_long(self, current_price):

        current_price = round(current_price, self.price_precision)

        self.long_adjusted_break_even_price = self.calculate_long_adjusted_break_even_price()

        if self.long_adjusted_break_even_price != 0 and current_price:
            self.long_pnl = round((current_price - self.long_adjusted_break_even_price) * self.long_qty, 2)
            pnl_percentage = round(
                ((current_price - self.long_adjusted_break_even_price) / self.long_adjusted_break_even_price) * 100, 2)
            logging.debug(f"long_pnl: {self.long_pnl}, long_pnl_percentage: {pnl_percentage}")

            return self.long_pnl

    def calculate_pnl_short(self, current_price):

        current_price = round(current_price, self.price_precision)

        self.short_adjusted_break_even_price = self.calculate_short_adjusted_break_even_price()

        if self.short_adjusted_break_even_price != 0 and current_price:
            self.short_pnl = round((self.short_adjusted_break_even_price - current_price) * self.short_qty, 2)
            pnl_percentage = round(
                ((self.short_adjusted_break_even_price - current_price) / self.short_adjusted_break_even_price) * 100, 2)
            logging.debug(f"short_pnl: {self.short_pnl}, short_pnl_percentage: {pnl_percentage}")

            return self.short_pnl

class TradeMonitorBase:

    def __init__(self, symbols: List[str]):
        self.symbols = symbols
        self.positions: Dict[str, SymbolPosition] = {symbol: SymbolPosition() for symbol in symbols}

    def on_message(self, message):
        pass


if __name__ == '__main__':
    # SymbolPosition
    symbol_position = SymbolPosition()

    symbol_position.long_qty = Decimal(12485)
    symbol_position.long_entry = Decimal(0.03327)
    symbol_position.long_break_even_price = Decimal(0.03328)
    symbol_position.calculate_long_adjusted_break_even_price()
    symbol_position.calculate_pnl_long(Decimal(0.03327))
    print(symbol_position.long_pnl)

    symbol_position.short_qty = Decimal(12485)
    symbol_position.short_entry = Decimal(0.03328)
    symbol_position.short_break_even_price = Decimal(0.03327)
    symbol_position.calculate_short_adjusted_break_even_price()
    symbol_position.calculate_pnl_short(Decimal(0.03328))
    print(symbol_position.short_pnl)

    total_pnl = symbol_position.long_pnl + symbol_position.short_pnl
    print(f"Total PnL: {total_pnl}")

