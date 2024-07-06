import json
import logging
from decimal import Decimal
from pprint import pprint

import asyncio
from decimal import Decimal

from binance.websocket.um_futures.websocket_client import UMFuturesWebsocketClient
from sqlmodel.ext.asyncio.session import AsyncSession

from core.binance_futures import client, check_position
from core.db_async import async_engine
from core.models.orders import OrderStatus, OrderType, Order
from core.schemas.events.account_update import AccountUpdateEvent, UpdateData
from core.schemas.events.agg_trade import AggregatedTradeEvent
from core.schemas.events.order_trade_update import OrderTradeUpdateEvent, OrderTradeUpdate
from core.views.handle_orders import db_get_order_binance_id
from trade.orders.create import grid_make_limit_and_tp_order


class TradeMonitor:
    def __init__(self, symbol):
        self.symbol = symbol

        self.long_position_qty = Decimal(0)
        self.long_entry_price = Decimal(0)
        self.short_position_qty = Decimal(0)
        self.short_entry_price = Decimal(0)
        self.client = UMFuturesWebsocketClient(on_message=self.on_message)

        self.long_pnl = 0
        self.short_pnl = 0

    async def monitor_events(self):
        position_long, position_short = await check_position(self.symbol)
        if position_long:
            self.long_position_qty = position_long.positionAmt
            self.long_entry_price = position_long.breakEvenPrice
            print(f"+LONG -> qty: {self.long_position_qty}, Entry price: {self.long_entry_price}")

        if position_short:
            self.short_position_qty = position_short.positionAmt
            self.short_entry_price = position_short.breakEvenPrice
            print(f"-SHORT -> qty: {self.short_position_qty}, Entry price: {self.short_entry_price}")

        listen_key = client.new_listen_key().get('listenKey')
        self.client.agg_trade(self.symbol)
        self.client.user_data(listen_key=listen_key)

    def on_message(self, ws, msg):
        asyncio.run(self.handle_message(msg))

    async def handle_message(self, msg):
        print(msg)
        message_dict = json.loads(msg)
        event_type = message_dict.get('e')
        if event_type == 'aggTrade':
            await self.handle_agg_trade(message_dict)
        elif event_type == 'ORDER_TRADE_UPDATE':
            await self.handle_order_update(message_dict)
        elif event_type == 'ACCOUNT_UPDATE':
            await self.handle_account_update(message_dict)

    async def handle_agg_trade(self, message_dict):
        event = AggregatedTradeEvent.parse_obj(message_dict)
        trade_price = Decimal(event.price)

        self.long_pnl = 0
        print(f'-----{event.symbol}------')

        if self.long_position_qty != 0:
            self.long_pnl = round((trade_price - self.long_entry_price) * self.long_position_qty, 2)
            print(f"+Long PNL: {self.long_pnl}")
        if self.short_position_qty != 0:
            self.short_pnl = round((trade_price - self.short_entry_price) * self.short_position_qty, 2)
            print(f"-Short PNL: {self.short_pnl}")

            _diff = self.long_pnl + self.short_pnl
            if _diff > 0:
                print(f"=Profit: {_diff} USDT")
                # close all positions, orders all
            else:
                print(f"=Loss: {_diff} USDT")

    async def handle_order_update(self, message_dict):
        async with AsyncSession(async_engine) as session:
            order_bi: OrderTradeUpdate = OrderTradeUpdate.parse_obj(message_dict.get('o'))
            if order_bi.order_status in ['FILLED', 'CANCELED', 'REJECTED']:
                print(f"Order status: {order_bi.order_status}")
                print(f"Order side: {order_bi.side}")
                print(f"Order type: {order_bi.order_type}")
                print(f"Order position side: {order_bi.position_side}")
                print(f"Order quantity: {order_bi.original_quantity}")
                print(f"Order price: {order_bi.original_price}")

                order_binance_id = order_bi.order_id
                print(f"Order binance_id: {order_binance_id}")

                order = await db_get_order_binance_id(order_binance_id, session)
                if not order:
                    print(f"!!!!!Order not found in DB - {order_binance_id}")
                    return

                order.binance_id = order_binance_id
                order.status = order_bi.order_status
                order.binance_status = order_bi.order_status

                if order.type == OrderType.LIMIT and order_bi.order_status == 'FILLED':
                    print(f"Order {order_binance_id} LIMIT start grid_make_limit_and_tp_order")
                    await grid_make_limit_and_tp_order(webhook_id=order.webhook_id, session=session)

    async def handle_account_update(self, message_dict):
        data = UpdateData.parse_obj(message_dict['a'])
        for position in data.positions:

            if position.position_side == 'LONG':
                self.long_position_qty = Decimal(position.position_amount)
                self.long_entry_price = Decimal(position.breakeven_price)
                print(f'UPDATE Long PNL: {position.unrealized_pnl}')
                pprint(position)
            elif position.position_side == 'SHORT':
                self.short_position_qty = Decimal(position.position_amount)
                self.short_entry_price = Decimal(position.breakeven_price)
                print(f'UPDATE Short PNL: {position.unrealized_pnl}')
                pprint(position)


async def main():
    trade_monitor = TradeMonitor('JOEUSDT')
    await trade_monitor.monitor_events()


if __name__ == '__main__':
    asyncio.run(main())
