import asyncio
from typing import List, Dict
from decimal import Decimal
import json

import sentry_sdk
from binance import AsyncClient, BinanceSocketManager
from binance.exceptions import BinanceAPIException

from core.models.binance_position import PositionStatus, BinancePosition
from core.models.monitor import SymbolPosition
from core.models.orders import OrderType, OrderPositionSide, Order
from core.schemas.events.agg_trade import AggregatedTradeEvent
from core.schemas.events.order_trade_update import OrderTradeUpdate
from core.schemas.events.account_update import UpdateData
import json
from decimal import Decimal
from config import get_settings
from core.schemas.position import LongPosition, ShortPosition
from core.views.handle_orders import get_webhook_last, db_get_order_binance_position_id
from core.views.handle_positions import get_exist_position, save_position
from flows.order_new_flow import order_new_flow
from flows.tasks.binance_futures import client, check_position, get_order_id
from core.logger import logger
from flows.agg_trade_flow import close_positions
from flows.order_filled_flow import order_filled_flow
from flows.order_cancel_flow import order_cancel_flow


class TradeMonitor:
    def __init__(self, client: AsyncClient, symbols: List[str]):
        self.client = client
        self.bsm = BinanceSocketManager(client)
        self.symbols = symbols
        self.positions: Dict[str, SymbolPosition] = {symbol: SymbolPosition() for symbol in symbols}

    async def start_monitor_events(self):
        tasks = [self.monitor_symbol(symbol) for symbol in self.symbols]
        await asyncio.gather(*tasks)

    async def monitor_symbol(self, symbol):
        async with self.bsm.futures_multiplex_socket([f'{symbol.lower()}@aggTrade']) as stream:
            while True:
                msg = await stream.recv()
                if msg:
                    await self.handle_message(msg)

    async def handle_message(self, message):
        message_dict = message.get('data')
        event_type = message_dict.get('e')
        if event_type == 'aggTrade':
            await self.handle_agg_trade(AggregatedTradeEvent.parse_obj(message_dict))
        elif event_type == 'ORDER_TRADE_UPDATE':
            await self.handle_order_update(OrderTradeUpdate.parse_obj(message_dict.get('o')))
        elif event_type == 'ACCOUNT_UPDATE':
            await self.handle_account_update(UpdateData.parse_obj(message_dict['a']))

    async def handle_agg_trade(self, event: AggregatedTradeEvent):
        position = self.positions.get(event.symbol)
        if position:
            current_price = Decimal(event.price)
            await self.process_trade_event(position, current_price)

    async def handle_order_update(self, event: OrderTradeUpdate):
        # Processing order updates here
        pass

    async def handle_account_update(self, event: UpdateData):
        # Process account updates here
        pass

    async def process_trade_event(self, position, current_price):
        # Process trade event logic
        pass


async def main():
    client = await AsyncClient.create()
    symbols = ['1000FLOKIUSDT']  # Example symbols
    trade_monitor = TradeMonitor(client, symbols)
    await trade_monitor.start_monitor_events()


if __name__ == '__main__':
    asyncio.run(main())
