import asyncio
from functools import lru_cache

from binance.um_futures import UMFutures
import sys
import logging

from fastapi import HTTPException

sys.path.append('..')
sys.path.append('.')
from core.models.orders import Order, OrderType

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


async def create_order_binance(order: Order):
    """
    https://binance-docs.github.io/apidocs/futures/en/#new-order-trade

    :param order:
    :return:
    """

    try:
        # todo: надо вынести в базу данные по точности числа quantity
        quantity, price = get_symbol_price_and_quantity_by_precisions(order.symbol, order.quantity)

        order_params = {
            "symbol": order.symbol,
            "type": order.type.value,
            "quantity": quantity,
            "positionSide": order.position_side.value,
            "side": order.side.value
        }

        if order.type != OrderType.MARKET:
            order_params["price"] = price

        response = client.new_order(**order_params)

        logging.info(f"Order created successfully: {response}")
        return response['orderId']
    except Exception as e:
        logging.error(f"Failed to create order: {e}")
        raise HTTPException(status_code=500, detail="Failed to create order")


async def wait_order(symbol):
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
        orders = client.get_orders(symbol=symbol)
        if orders:
            logging.info(f"Orders: {orders}")
            return orders
    except Exception as e:
        logging.error(f"Failed to monitor order: {e}")
        raise HTTPException(status_code=500, detail="Failed to monitor order")

    return None


async def check_position_side_dual() -> bool:
    try:
        dual_side_position = client.get_position_mode()

        if dual_side_position:
            logging.info(f"Position side dual: {dual_side_position}")
            return True
        else:
            logging.info(f"No position side dual found")
            r = client.change_position_mode(dualSidePosition=True)

            if r['code'] == 200:
                logging.info(f"Position side dual changed to True")
            else:
                logging.error(f"Не получилось сменить позицию, проверье настройки Binance!: {r}")
                return False

            # sleep1
            await asyncio.sleep(1)
            dual_side_position = client.get_position_mode()
            logging.info(f"Position side dual: {dual_side_position}")

            return True

    except Exception as e:
        logging.error(f"Failed to get position side dual: {e}")
        raise HTTPException(status_code=500, detail="Failed to get position side dual")


async def check_position(symbol: str, side: str = 'LONG'):
    "GET /fapi/v2/positionRisk"
    """
    https://binance-docs.github.io/apidocs/futures/en/#position-information-v2-user_data
    
    Result For Hedge position mode:

[
    {
        "symbol": "BTCUSDT",
        "positionAmt": "0.001",
        "entryPrice": "22185.2",
        "breakEvenPrice": "0.0",  
        "markPrice": "21123.05052574",
        "unRealizedProfit": "-1.06214947",
        "liquidationPrice": "19731.45529116",
        "leverage": "4",
        "maxNotionalValue": "100000000",
        "marginType": "cross",
        "isolatedMargin": "0.00000000",
        "isAutoAddMargin": "false",
        "positionSide": "LONG",
        "notional": "21.12305052",
        "isolatedWallet": "0",
        "updateTime": 1655217461579
    },
    {
        "symbol": "BTCUSDT",
        "positionAmt": "0.000",
        "entryPrice": "0.0",
        "breakEvenPrice": "0.0",  
        "markPrice": "21123.05052574",
        "unRealizedProfit": "0.00000000",
        "liquidationPrice": "0",
        "leverage": "4",
        "maxNotionalValue": "100000000",
        "marginType": "cross",
        "isolatedMargin": "0.00000000",
        "isAutoAddMargin": "false",
        "positionSide": "SHORT",
        "notional": "0",
        "isolatedWallet": "0",
        "updateTime": 0
    }
]
"""

    try:
        positions = client.get_position_risk(symbol=symbol)
        if positions:
            logging.info(f"Position: {positions}")

            # if LONG return entryPrice, with next
            position = next((p for p in positions if p['positionSide'] == side), None)

            return position

    except Exception as e:
        logging.error(f"Failed to get position: {e}")
        raise HTTPException(status_code=500, detail="Failed to get position")

    return None


async def wait_order_id(symbol, order_id):
    try:
        print(f"Monitoring order {symbol}: {order_id}")
        while True:
            orders = client.get_open_orders(symbol=symbol, order_id=order_id)

            for order in orders:
                print(order)

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


def on_message(ws, msg):
    logging.info(f"Received message: {msg}")
    if msg['e'] == 'ORDER_TRADE_UPDATE':
        order_status = msg['o']['X']
        logging.info(f"Order status: {order_status}")
        if order_status in ['FILLED', 'CANCELED', 'REJECTED']:
            logging.info(f"Order completed with status: {order_status}")



def monitor_ws(symbol):
    from binance.websocket.um_futures.websocket_client import UMFuturesWebsocketClient

    listen_key = client.new_listen_key().get('listenKey')
    ws_client = UMFuturesWebsocketClient(on_message=on_message)

    # Подключаемся к WebSocket и подписываемся на данные пользователя
    ws_client.user_data(
        listen_key=listen_key,
        symbol=symbol
    )

    # данные по цене
    # ws_client.agg_trade(
    #     symbol=symbol,
    #     action=UMFuturesWebsocketClient.ACTION_SUBSCRIBE
    #
    # )



if __name__ == "__main__":
    # print(get_symbol_price_and_quantity_by_precisions("JOEUSDT", 0.0001))
    # print(get_symbol_price_and_quantity_by_precisions("JOEUSDT", 0.00000001))
    # print(get_symbol_price_and_quantity_by_precisions("JOEUSDT", 60))

    monitor_ws("JOEUSDT")
