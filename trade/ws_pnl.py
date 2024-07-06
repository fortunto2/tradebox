import json
import logging
from decimal import Decimal
from pprint import pprint

from binance.websocket.um_futures.websocket_client import UMFuturesWebsocketClient
from pydantic import ValidationError
from sqlmodel.ext.asyncio.session import AsyncSession

from core.binance_futures import create_order_binance, monitor_ws, client, check_position
from core.db_async import get_async_session, async_engine, async_session
from core.models.orders import OrderStatus, OrderType
from core.models.orders import Order as OrderBinance
from core.schemas.events.account_update import AccountUpdateEvent, UpdateData
from core.schemas.events.agg_trade import AggregatedTradeEvent
from core.schemas.events.order_trade_update import OrderTradeUpdateEvent, Order
from trade.create_orders import get_grid_orders, grid_make_limit_and_tp_order
from trade.handle_orders import db_get_order

# Глобальные переменные для хранения информации о длинной и короткой позициях
long_position_qty = Decimal(0)
long_entry_price = Decimal(0)
short_position_qty = Decimal(0)
short_entry_price = Decimal(0)


def on_message(ws, msg):
    global long_position_qty, long_entry_price, short_position_qty, short_entry_price

    message_dict = json.loads(msg)
    event_type = message_dict.get('e')

    # session = AsyncSession(async_engine)
    # session = async_session

    if event_type == 'aggTrade':
        event = AggregatedTradeEvent.parse_obj(message_dict)
        trade_price = Decimal(event.price)

        long_pnl = 0
        print(f'-----{event.symbol}------')

        if long_position_qty != 0:
            long_pnl = round((trade_price - long_entry_price) * long_position_qty, 2)
            print(f"+Long PNL: {long_pnl}")
        if short_position_qty != 0:
            short_pnl = round((trade_price - short_entry_price) * short_position_qty, 2)
            print(f"-Short PNL: {short_pnl}")

            _diff = short_pnl + long_pnl
            if _diff > 0:
                print(f"=Profit: {_diff} USDT")
                #close all positions, orders all
            else:
                print(f"=Loss: {_diff} USDT")

    elif event_type == 'ORDER_TRADE_UPDATE':
        order_bi: Order = Order.parse_obj(message_dict.get('o'))
        if order_bi.order_status in ['FILLED', 'CANCELED', 'REJECTED']:
            print(f"Order status: {order_bi.order_status}")
            print(f"Order side: {order_bi.side}")
            print(f"Order type: {order_bi.order_type}")
            print(f"Order position side: {order_bi.position_side}")
            print(f"Order quantity: {order_bi.original_quantity}")
            print(f"Order price: {order_bi.original_price}")

            order = asyncio.run(db_get_order(order_bi.order_id))
            order.binance_id = order_bi.order_id
            order.status = order_bi.order_status
            order.binance_status = order_bi.order_status

            if order.type == OrderType.LIMIT:
                print(f"Order {order.order_id} LIMIT start grid_make_limit_and_tp_order")
                asyncio.run(grid_make_limit_and_tp_order(webhook_id=order.webhook_id))

            # await session.commit()


    elif event_type == 'ACCOUNT_UPDATE':
        data = UpdateData.parse_obj(message_dict['a'])
        for position in data.positions:

            if position.position_side == 'LONG':
                long_position_qty = Decimal(position.position_amount)
                long_entry_price = Decimal(position.breakeven_price)
                print(f'UPDATE Long PNL: {position.unrealized_pnl}')
                pprint(position)
            elif position.position_side == 'SHORT':
                short_position_qty = Decimal(position.position_amount)
                short_entry_price = Decimal(position.breakeven_price)
                print(f'UPDATE Short PNL: {position.unrealized_pnl}')
                pprint(position)


async def monitor_symbol(symbol: str):
    global long_position_qty, long_entry_price, short_position_qty, short_entry_price

    position_long, position_short = await check_position(symbol)
    if position_long:
        long_position_qty = position_long.positionAmt
        long_entry_price = position_long.breakEvenPrice
        print(f"+LONG -> qty: {long_position_qty}, Entry price: {long_entry_price}")
    if position_short:
        short_position_qty = position_short.positionAmt
        short_entry_price = position_short.breakEvenPrice
        print(f"-SHORT -> qty: {short_position_qty}, Entry price: {short_entry_price}")

    listen_key = client.new_listen_key().get('listenKey')
    ws_client = UMFuturesWebsocketClient(on_message=on_message)
    ws_client.agg_trade(symbol=symbol)
    ws_client.user_data(listen_key=listen_key)


async def monitor_orders(symbol):
    """
    Monitor orders and update their status based on websocket messages.
    """
    # async with AsyncSession(async_engine) as session:
    orders = await monitor_symbol(symbol=symbol)


if __name__ == '__main__':
    import asyncio

    loop = asyncio.get_event_loop()
    if loop.is_running():
        asyncio.run(monitor_orders(symbol='JOEUSDT'))
    else:
        loop.run_until_complete(monitor_orders(symbol='JOEUSDT'))
