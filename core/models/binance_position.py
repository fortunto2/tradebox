import enum
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional, Literal, List

from sqlalchemy import Index
from sqlmodel import SQLModel, Field, Relationship

from core.logger import logger
from core.models.orders import OrderPositionSide, Order
from core.models.webhook import WebHook
from core.models.binance_symbol import BinanceSymbol

class PositionStatus(enum.Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    # UPDATED = "UPDATED"


class BinancePosition(SQLModel, table=True):
    id: int = Field(default=None, primary_key=True)
    webhook_id: Optional[int] = Field(default=None, foreign_key="webhook.id", index=True)
    webhook: "WebHook" = Relationship(back_populates="binance_positions")

    symbol: str = Field(default=None, foreign_key="binancesymbol.symbol", index=True)
    symbol_info: "BinanceSymbol" = Relationship(back_populates="positions")

    position_side: OrderPositionSide
    position_qty: Decimal = Field(default=0)
    entry_price: Decimal = Field(default=0)
    entry_break_price: Decimal = Field(default=0)
    status: PositionStatus = PositionStatus.OPEN

    pnl: Decimal = Field(default=0)
    activation_price: Decimal = Field(default=0)

    orders: List[Order] = Relationship(sa_relationship_kwargs={"back_populates": "binance_position"})

    created_at: datetime = Field(
        default_factory=datetime.now,
        nullable=False,
    )
    updated_at: datetime = Field(
        default_factory=datetime.now,
        nullable=False,
    )

    closed_at: Optional[datetime] = Field(default=None)

    # filled_orders: List[Order] = Relationship(
    #     sa_relationship_kwargs={
    #         "primaryjoin": "and_(Order.binance_position_id == BinancePosition.id, Order.status == 'FILLED')",
    #         "overlaps": "binance_position,orders"
    #     }
    # )

    __table_args__ = (
        Index("ix_binanceposition_uniq", "webhook_id", "symbol", "status", "position_side", unique=True),
    )

    # todo: при записи все цены округлять по precision инструмента

    def calculate_precision_based_value(self, some_value: Decimal) -> Decimal:
        """Пример использования quantity_precision из BinanceSymbol"""
        return self.symbol_info.adjust_precision(some_value)

    def calculate_adjusted_break_even_price(self) -> Decimal:
        """
        Для расчета, когда закрываем позицию.
        Для других случаев, если нужно, PnL брать из Binance.
        """
        adjusted_break_even_price = self.entry_price
        # adjusted_break_even_price = self.entry_price + (self.entry_price * Decimal(0.1)) / 100

        # if self.entry_break_price is not None and self.entry_price is not None:
        #     if self.position_side == OrderPositionSide.LONG:
        #         # Логика для long позиции
        #         if self.entry_break_price != self.entry_price:
        #             percentage_difference = ((self.entry_break_price - self.entry_price) / self.entry_price) * 100
        #
        #             adjusted_percentage = percentage_difference * 2
        #             adjusted_break_even_price = self.symbol_info.adjust_precision(
        #                 self.entry_break_price + (self.entry_price * (adjusted_percentage / 100)),
        #                 self.symbol_info.price_precision
        #             )
        #             logger.info(
        #                 f"LONG: {self.position_side.value} adjusted_percentage: {round(adjusted_percentage, 2)}%, new_break_even_price: {adjusted_break_even_price}")
        #
        #     elif self.position_side == OrderPositionSide.SHORT:
        #         # Логика для short позиции
        #         if self.entry_break_price != self.entry_price:
        #             percentage_difference = ((self.entry_price - self.entry_break_price) / self.entry_price) * 100
        #             adjusted_percentage = percentage_difference * 2
        #             adjusted_break_even_price = self.symbol_info.adjust_precision(
        #                 self.entry_break_price - (self.entry_price * (adjusted_percentage / 100)),
        #                 self.symbol_info.price_precision
        #             )
        #
        #             logger.info(f"SHORT: {self.position_side.value} adjusted_percentage: {round(adjusted_percentage, 2)}%, new_break_even_price: {adjusted_break_even_price}")
        return adjusted_break_even_price

    def calculate_pnl(self, current_price: Decimal) -> Decimal:
        # надо брать из event не реализованный пнл
        pass

    # def calculate_pnl(self, current_price: Decimal) -> Decimal:
    #     """
    #     Расчет прибыли и убытков (PnL) на основе текущей цены и пересчитанной цены безубыточности.
    #     """
    #     current_price = self.symbol_info.adjust_precision(current_price, self.symbol_info.price_precision)
    #     adjusted_break_even_price = self.calculate_adjusted_break_even_price()
    #
    #     if adjusted_break_even_price != 0 and current_price:
    #         if self.position_side == OrderPositionSide.LONG:
    #             pnl = self.symbol_info.adjust_precision(
    #                 (current_price - adjusted_break_even_price) * self.position_qty,
    #                 2
    #             )
    #         elif self.position_side == OrderPositionSide.SHORT:
    #             pnl = self.symbol_info.adjust_precision(
    #                 (adjusted_break_even_price - current_price) * self.position_qty,
    #                 2
    #             )
    #
    #         pnl_percentage = round(
    #             ((current_price - adjusted_break_even_price) / adjusted_break_even_price) * 100, 2)
    #         logger.info(f"{self.position_side.value}_pnl: {pnl}, {self.position_side.value}_pnl_percentage: {pnl_percentage}")
    #
    #         return pnl


if __name__ == '__main__':
    # Создаем объект символа BinanceSymbol
    symbol_info = BinanceSymbol(
        symbol="BTCUSDT",
        quantity_precision=6,
        price_precision=6
    )

    # Создаем объект для Long позиции, связанный с символом
    position = BinancePosition(
        symbol="BTCUSDT",
        symbol_info=symbol_info,
        position_side=OrderPositionSide.LONG,
        position_qty=Decimal(12485),
        entry_price=Decimal(0.03327),
        entry_break_price=Decimal(0.03328),
    )

    # Выполняем расчет PnL для Long позиции
    pnl_long = position.calculate_pnl(Decimal(0.03327))
    print(f"Long PnL: {pnl_long}")

    # Создаем объект для Short позиции, связанный с символом
    position = BinancePosition(
        symbol="BTCUSDT",
        symbol_info=symbol_info,
        position_side=OrderPositionSide.SHORT,
        position_qty=Decimal(12485),
        entry_price=Decimal(0.03328),
        entry_break_price=Decimal(0.03327),
    )

    # Выполняем расчет PnL для Short позиции
    pnl_short = position.calculate_pnl(Decimal(0.03328))
    print(f"Short PnL: {pnl_short}")
