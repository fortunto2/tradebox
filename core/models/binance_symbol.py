from decimal import Decimal, ROUND_DOWN
from typing import List

from sqlmodel import SQLModel, Field, Relationship



class BinanceSymbol(SQLModel, table=True):
    symbol: str = Field(default=None, primary_key=True)
    quantity_precision: int
    price_precision: int

    positions: List["BinancePosition"] = Relationship(back_populates="symbol_info")

    def adjust_precision(self, value: Decimal, precision: int) -> Decimal:
        """Корректировка точности значения."""
        quantize_str = '1.' + '0' * precision if precision > 0 else '1'
        return value.quantize(Decimal(quantize_str), rounding=ROUND_DOWN)

    def adjust_quantity(self, quantity: Decimal) -> Decimal:
        """Корректировка точности количества на основе quantity_precision."""
        return self.adjust_precision(quantity, self.quantity_precision)

    def adjust_price(self, price: Decimal) -> Decimal:
        """Корректировка точности цены на основе price_precision."""
        return self.adjust_precision(price, self.price_precision)
