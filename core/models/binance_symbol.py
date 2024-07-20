from sqlmodel import SQLModel, Field


class BinanceSymbol(SQLModel, table=True):
    symbol: str = Field(default=None, primary_key=True)
    quantity_precision: int
    price_precision: int
