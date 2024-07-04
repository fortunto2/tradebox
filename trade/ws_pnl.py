import json
import logging
from pprint import pprint

from pydantic import ValidationError
from sqlmodel.ext.asyncio.session import AsyncSession

from core.binance_futures import create_order_binance, monitor_ws, client
from core.db_async import get_async_session, async_engine
from core.schemas.events.account_update import AccountUpdateEvent, UpdateData
from core.schemas.events.order_trade_update import OrderTradeUpdateEvent, Order


def on_message(ws, msg):
    print(f"Received message: {msg}")

    # Decode the JSON string message into a dictionary
    message_dict = json.loads(msg)

    # Determine the type of the event from the message and parse accordingly
    event_type = message_dict.get('e')
    if event_type == 'ORDER_TRADE_UPDATE':
        # Parse the message using the Order model
        order = Order.parse_obj(message_dict.get('o'))  # Assuming 'o' contains the order details
        # print(f"Order status: {order.order_status}")
        if order.order_status in ['FILLED', 'CANCELED', 'REJECTED']:
            # side, position_side, sttaus, quantity, price
            print(f"Order status: {order.order_status}")
            print(f"Order side: {order.side}")
            print(f"Order type: {order.order_type}")
            print(f"Order position side: {order.position_side}")
            print(f"Order quantity: {order.original_quantity}")
            print(f"Order price: {order.original_price}")

    elif event_type == 'ACCOUNT_UPDATE':
        # Parse the message using the AccountUpdateEvent model
        data = UpdateData.parse_obj(message_dict['a'])
        for position in data.positions:
            # print pnl and position info
            print(f'PNL: {position.unrealized_pnl}, Position: {position.position_side}')
            pprint(position.model_dump())

    # except json.JSONDecodeError:
    #     print("Failed to decode JSON message.")
    # except ValidationError as e:
    #     print(f"Validation error while parsing message: {e}")

async def monitor_symbol(symbol: str, session: AsyncSession):
    """
    Monitor a given symbol using websocket.
    """
    from binance.websocket.um_futures.websocket_client import UMFuturesWebsocketClient

    listen_key = client.new_listen_key().get('listenKey')
    ws_client = UMFuturesWebsocketClient(on_message=on_message)
    # ws_client = UMFuturesWebsocketClient(lambda ws, msg: on_message(ws, msg, session))
    ws_client.user_data(listen_key=listen_key, symbol=symbol)


async def monitor_orders(symbol):
    """
    Monitor orders and update their status based on websocket messages.
    """
    async with AsyncSession(async_engine) as session:
        orders = await monitor_symbol(symbol=symbol, session=session)


if __name__ == '__main__':
    import asyncio

    loop = asyncio.get_event_loop()
    if loop.is_running():
        asyncio.run(monitor_orders(symbol='JOEUSDT'))
    else:
        loop.run_until_complete(monitor_orders(symbol='JOEUSDT'))
