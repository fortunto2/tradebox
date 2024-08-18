import enum
from decimal import Decimal
from typing import Optional, Literal, Dict, List

from pydantic import field_validator
from sqlmodel import SQLModel, Field, JSON, Relationship, Column
from sqlmodel.ext.asyncio.session import AsyncSession

from core.models.orders import OrderPositionSide, OrderSide
from core.schemas.webhook import WebhookPayload, OpenOrder, Settings


class WebHook(SQLModel, table=True):
    id: Optional[int] = Field(primary_key=True)
    name: str
    side: OrderSide
    positionSide: OrderPositionSide
    symbol: str
    open: OpenOrder = Field(default_factory=dict, sa_column=Column(JSON))
    settings: Settings = Field(default_factory=dict, sa_column=Column(JSON))
    status: str = 'new'

    orders: List["Order"] = Relationship(back_populates="webhook")
    binance_positions: List["BinancePosition"] = Relationship(back_populates="webhook")

    def from_payload(self, payload):
        self.name = payload.name
        self.side = payload.side
        self.positionSide = payload.positionSide
        self.symbol = payload.symbol
        self.open = payload.open.dict()
        self.settings = payload.settings.dict()


async def save_webhook(payload: WebhookPayload, session: AsyncSession) -> WebHook:
    webhook = WebHook(
        name=payload.name,
        side=payload.side,
        positionSide=payload.positionSide,
        symbol=payload.symbol,
        open=payload.open.dict(),
        settings=payload.settings.dict()
    )
    y = session.add(webhook)
    x = await session.commit()
    return webhook
