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
from core.schemas.webhook import WebhookPayload
from core.views.handle_orders import db_get_order_binance_id
from trade.orders.orders_create import create_short_stop_loss_order
from trade.orders.orders_processing import grid_make_limit_and_tp_order, check_orders_in_the_grid, \
    open_short_position_loop


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

        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

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
        # Schedule the coroutine from a synchronous context using the instance's event loop
        if self.loop.is_closed():
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
        asyncio.run(self.handle_message(msg))

    async def handle_message(self, msg):
        print(msg)
        message_dict = json.loads(msg)
        event_type = message_dict.get('e')

        if event_type == 'aggTrade':
            event = AggregatedTradeEvent.parse_obj(message_dict)
            await self.handle_agg_trade(event)

        elif event_type == 'ORDER_TRADE_UPDATE':
            event = OrderTradeUpdate.parse_obj(message_dict.get('o'))
            await self.handle_order_update(event)

        elif event_type == 'ACCOUNT_UPDATE':
            event = UpdateData.parse_obj(message_dict['a'])
            await self.handle_account_update(event)

    async def handle_agg_trade(self, event: AggregatedTradeEvent):
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

    async def handle_order_update(self, event: OrderTradeUpdate):
        async with AsyncSession(async_engine) as session:
            if event.order_status == 'FILLED':
                print(f"Order status: {event.order_status}")
                print(f"Order side: {event.side}")
                print(f"Order type: {event.order_type}")
                print(f"Order position side: {event.position_side}")
                print(f"Order quantity: {event.original_quantity}")
                print(f"Order price: {event.original_price}")

                order_binance_id = event.order_id
                print(f"Order binance_id: {order_binance_id}")

                order: Order = await db_get_order_binance_id(order_binance_id, session)
                if not order:
                    print(f"!!!!!Order not found in DB - {order_binance_id}")
                    return

                order.binance_id = order_binance_id
                order.status = event.order_status
                order.binance_status = event.order_status
                await session.flush()


                webhook = order.webhook

                # todo rewrite all to sql model
                payload = WebhookPayload(
                    name=webhook.name,
                    side=order.side,
                    positionSide=order.position_side,
                    symbol=order.symbol,
                    open=webhook.open,
                    settings=webhook.settings
                )

                orders_in_the_grid = True

                filled_orders, grid_orders, grid = await check_orders_in_the_grid(
                    payload, order.webhook_id, session)

                # когда последний заканчивет сетку
                if len(filled_orders) >= len(grid):
                    print(f"stop: filled_orders {filled_orders} >= grid_orders {grid_orders}")
                    orders_in_the_grid = False

                if order.type == OrderType.LONG_LIMIT and orders_in_the_grid:
                    print(f"Order {order_binance_id} LIMIT start grid_make_limit_and_tp_order")

                    await grid_make_limit_and_tp_order(
                        webhook_id=order.webhook_id,
                        payload=payload,
                        session=session)

                if order.type == OrderType.SHORT_STOP_LOSS and not orders_in_the_grid:
                    print(f"Order {order_binance_id} HEDGE_STOP_LOSS start make_hedge_by_pnl")

                    # открытие позиции - виртуальный ордер
                    await open_short_position_loop(
                        payload=payload,
                        webhook_id=order.webhook_id,
                        session=session
                    )

                if order.type == OrderType.SHORT_LIMIT and not orders_in_the_grid:
                    # stop_price = Decimal(order.price) * (1 - Decimal(payload.settings.offset_short / 100))

                    short_stop_loss_order = await create_short_stop_loss_order(
                        symbol=payload.symbol,
                        sl_short=payload.settings.sl_short,
                        # quantity=quantity,
                        leverage=payload.open.leverage,
                        webhook_id=order.webhook_id,
                        session=session
                    )

                    print(f"Create short_stop_loss_order: {short_stop_loss_order.id}")

                await session.commit()

    async def handle_account_update(self, event: UpdateData):
        for position in event.positions:

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
