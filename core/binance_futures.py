import asyncio
from functools import lru_cache

from binance.um_futures import UMFutures
import sys
import logging

from fastapi import HTTPException

sys.path.append('..')
sys.path.append('.')

from config import settings

client = UMFutures()
# get server time
print(client.time())
client = UMFutures(key=settings.BINANCE_API_KEY, secret=settings.BINANCE_API_SECRET)
# Get account information
# print(client.account())


@lru_cache()
def get_symbol_info(symbol):
    exchange_info = client.exchange_info()
    for s in exchange_info['symbols']:
        if s['symbol'] == symbol:
            return s
    return None


from decimal import Decimal, ROUND_DOWN


def adjust_precision(value, precision):
    quantize_str = '1.' + '0' * precision if precision > 0 else '1'
    return value.quantize(Decimal(quantize_str), rounding=ROUND_DOWN)


@lru_cache()
def get_symbol_price_and_quantity_by_precisions(symbol, quantity):
    symbol_info = get_symbol_info(symbol)
    if not symbol_info:
        raise ValueError(f"Symbol {symbol} not found in exchange info")

    quantity_precision = 0
    price_precision = 8

    for filter in symbol_info['filters']:
        if filter['filterType'] == 'LOT_SIZE':
            quantity_precision = int(filter['stepSize'].find('1') - 1)
        if filter['filterType'] == 'PRICE_FILTER':
            price_precision = int(filter['tickSize'].find('1') - 1)

    print("quantity_precision: ", quantity_precision)
    print("price_precision : ", price_precision)

    price = client.ticker_price(symbol).get('price')
    print(price)

    # Приведение quantity и price к Decimal и корректировка точности
    quantity = adjust_precision(Decimal(quantity), quantity_precision)
    price = adjust_precision(Decimal(price), price_precision)

    return quantity, price


async def create_order(order):
    """
    https://binance-docs.github.io/apidocs/futures/en/#new-order-trade

    :param order:
    :return:
    """

    try:
        quantity, price = get_symbol_price_and_quantity_by_precisions(order["symbol"], order["quantity"])

        response = client.new_order(
            symbol=order["symbol"],
            type='MARKET',
            quantity=quantity,
            positionSide='LONG',
            side=order["side"],
            # price=price
        )

        logging.info(f"Order created successfully: {response}")
        return response['orderId']
    except Exception as e:
        logging.error(f"Failed to create order: {e}")
        raise HTTPException(status_code=500, detail="Failed to create order")


async def wait_order(symbol, order_id=None):
    """
    Monitor an order status by its ID.

    Order Status
        NEW
        PARTIALLY_FILLED
        FILLED
        CANCELED
        EXPIRED
        EXPIRED_IN_MATCH

    :param symbol: The symbol of the order to monitor.
    :param order_id: The ID of the order to monitor.
    :return: The order status.
    """
    try:
        while True:
            orders = client.get_orders(symbol=symbol)

            for order in orders:
                print(order)
                if order['orderId'] == order_id:

                    if order['status'] in ['FILLED', 'CANCELED', 'REJECTED']:
                        logging.info(f"Order {order_id} is {order['status']}")
                        return order

            await asyncio.sleep(1)  # Adjust the sleep interval as needed.
    except Exception as e:
        logging.error(f"Failed to monitor order: {e}")
        raise HTTPException(status_code=500, detail="Failed to monitor order")


async def check_open_orders(symbol):
    """
    Monitor all open orders.

    :param symbol: The symbol of the order to monitor.
    :return: The order status.
    """
    try:
        orders = client.get_orders(symbol=symbol)

        if orders:
            logging.info(f"Orders: {orders}")
            return orders
        else:
            logging.info(f"No orders found")
            return None

    except Exception as e:
        logging.error(f"Failed to monitor order: {e}")
        raise HTTPException(status_code=500, detail="Failed to monitor order")



def get_current_price(symbol: str) -> Decimal:
    try:
        ticker = client.ticker_price(symbol)
        return Decimal(ticker.get('price'))
    except Exception as e:
        logging.error(f"Failed to get current price: {e}")
        raise HTTPException(status_code=500, detail="Failed to get current price")


def on_message(msg):
    logging.info(f"Received message: {msg}")
    if msg['e'] == 'ORDER_TRADE_UPDATE':
        order_status = msg['o']['X']
        logging.info(f"Order status: {order_status}")
        if order_status in ['FILLED', 'CANCELED', 'REJECTED']:
            logging.info(f"Order completed with status: {order_status}")


def monitor_ws(symbol):
    from binance.websocket.um_futures.websocket_client import UMFuturesWebsocketClient

    listen_key = client.new_listen_key()
    ws_client = UMFuturesWebsocketClient(on_message=on_message)

    ws_client.subscribe(listen_key)

    ws_client.user_data(listen_key)

    ws_client.agg_trade(
        symbol=symbol,
        action=ws_client.ACTION_SUBSCRIBE
    )



if __name__ == "__main__":
    # print(get_symbol_price_and_quantity_by_precisions("JOEUSDT", 0.0001))
    # print(get_symbol_price_and_quantity_by_precisions("JOEUSDT", 0.00000001))
    # print(get_symbol_price_and_quantity_by_precisions("JOEUSDT", 60))

    monitor_ws("JOEUSDT")
