
from datetime import timedelta

from time import sleep, time


from binance.error import ClientError
from binance.um_futures import UMFutures
import sys
import logging

from fastapi import HTTPException
from prefect import task, tags
from prefect.tasks import task_input_hash
from sqlmodel import select


from core.clients.db_sync import SessionLocal, execute_sqlmodel_query_single
from core.models.binance_symbol import BinanceSymbol
from core.schemas.position import LongPosition, ShortPosition

sys.path.append('../..')
sys.path.append('../../core')
from core.models.orders import Order, OrderType, OrderPositionSide

from config import settings

client = UMFutures()
# get server time
print(client.time())
client = UMFutures(key=settings.BINANCE_API_KEY, secret=settings.BINANCE_API_SECRET)

import base64


def encode_order_id(order_id):
    encoded = base64.urlsafe_b64encode(order_id.encode()).decode()
    return encoded


def decode_order_id(encoded_id):
    decoded = base64.urlsafe_b64decode(encoded_id.encode()).decode()
    return decoded


# Get account information
# print(client.account())


@task(cache_key_fn=task_input_hash, cache_expiration=timedelta(days=1))
def get_symbol_info(symbol):
    exchange_info = client.exchange_info()
    for s in exchange_info['symbols']:
        if s['symbol'] == symbol:
            return s
    return None


from decimal import Decimal, ROUND_DOWN
from functools import lru_cache


def adjust_precision(value, precision):
    quantize_str = '1.' + '0' * precision if precision > 0 else '1'
    return value.quantize(Decimal(quantize_str), rounding=ROUND_DOWN)


@lru_cache(maxsize=128)
def get_symbol_quantity_and_precisions(symbol):
    """
    Получает precision данные для символа с кэшированием в памяти.
    Кэш: 128 символов (достаточно для большинства случаев).
    Данные практически никогда не меняются, поэтому безопасно кэшировать.
    """
    def query_func(session_local):
        query = select(BinanceSymbol).where(BinanceSymbol.symbol == symbol)
        result = session_local.exec(query)
        return result.first()

    bs = execute_sqlmodel_query_single(query_func)
    if not bs:

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
        with SessionLocal() as session:
            bs = BinanceSymbol(symbol=symbol, quantity_precision=quantity_precision, price_precision=price_precision)
            session.add(bs)
            session.commit()
            quantity_precision = bs.quantity_precision
            price_precision = bs.price_precision
    else:
        quantity_precision = bs.quantity_precision
        price_precision = bs.price_precision

    return quantity_precision, price_precision


def get_symbol_price_and_quantity_by_precisions(symbol, quantity, price=None):
    quantity_precision, price_precision = get_symbol_quantity_and_precisions(symbol)

    if price is None:
        price = client.ticker_price(symbol).get('price')
    print(price)

    # Приведение quantity и price к Decimal и корректировка точности
    quantity = adjust_precision(Decimal(quantity), quantity_precision)
    price = adjust_precision(Decimal(price), price_precision)

    return quantity, price


@task(
    name=f'create_order_binance',
    task_run_name='create_order_{order.side.value}_{order.type.value}'
)
async def create_order_binance(order: Order, return_full_response=False, trail_follow_price=None):
    """
    https://binance-docs.github.io/apidocs/futures/en/#new-order-trade

    :param trail_follow_price: just for LONG_TRAILING_STOP_MARKET
    :param return_full_response:
    :param order:
    :return:
    """

    with tags(order.symbol, order.side.value, order.type.value, order.position_side.value):

        # todo: надо вынести в базу данные по точности числа quantity
        quantity, price = get_symbol_price_and_quantity_by_precisions(order.symbol, order.quantity, order.price)

        hashed_order_id = f"{order.symbol}_{order.id}_{int(time())}"

        order_params = {
            "symbol": order.symbol,
            "type": order.type.value,
            "quantity": quantity,
            "positionSide": order.position_side.value,
            "side": order.side.value,
            # 'newClientOrderId': hashed_order_id
        }

        if order.type == OrderType.LONG_MARKET or order.type == OrderType.SHORT_MARKET:
            order_params["type"] = 'MARKET'
        elif order.type == OrderType.SHORT_LIMIT:
            order_params["stopPrice"] = price
            order_params["price"] = price
            order_params["type"] = 'STOP'
        elif order.type in [OrderType.SHORT_MARKET_STOP_LOSS, OrderType.SHORT_MARKET_STOP_OPEN]:
            order_params["stopPrice"] = price
            order_params["type"] = 'STOP_MARKET'
        elif order.type == OrderType.LONG_TRAILING_STOP_MARKET:
            if order_params["callbackRate"] < 0.1:
                logging.error("callbackRate must be greater than 0.1")
                order_params["callbackRate"] = 0.1
            order_params["callbackRate"] = trail_follow_price
            order_params["type"] = 'TRAILING_STOP_MARKET'
            order_params["activationPrice"] = price
        else:
            order_params["price"] = price
            order_params["timeInForce"] = "GTC"
            order_params["type"] = 'LIMIT'

        try:
            response = client.new_order(**order_params)

            logging.info(f"Order created successfully: {response}")
            if return_full_response:
                return response
            return str(response['orderId'])

        except ClientError as e:
            # if e.error_code == -2021:
            logging.error(e.error_message)
            return None


# @task
def cancel_order_binance(symbol, order_id):
    """
    https://binance-docs.github.io/apidocs/futures/en/#cancel-order-trade

    :param symbol:
    :param order_id:
    :return:
    """
    response = client.cancel_order(symbol=symbol, orderId=order_id)
    logging.info(f"Order canceled successfully: {response}")
    return response


# @task
def change_leverage(symbol: str, leverage: int):
    """
    Устанавливаем плече в начале вебхука
    :param symbol:
    :param leverage:
    :return:
    """
    response = client.change_leverage(symbol=symbol, leverage=leverage)
    logging.warning(f"change_leverage: {response}")
    return response


def check_position_side_dual() -> bool:
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

            sleep(1)
            dual_side_position = client.get_position_mode()
            logging.info(f"Position side dual: {dual_side_position}")

            return True

    except Exception as e:
        logging.error(f"Failed to get position side dual: {e}")
        raise HTTPException(status_code=500, detail="Failed to get position side dual")


# @task(
#     name=f'check_position',
#     retries=3,
#     retry_delay_seconds=5
# )
def check_position(symbol: str) -> (LongPosition, ShortPosition):
    "GET /fapi/v2/positionRisk"
    """
    https://binance-docs.github.io/apidocs/futures/en/#position-information-v2-user_data
    """

    positions = client.get_position_risk(symbol=symbol)
    if positions:
        print(f"Position: {positions}")

        # if LONG return entryPrice, with next
        position_long = next((LongPosition(**p) for p in positions if p['positionSide'] == 'LONG'), None)
        position_short = next((ShortPosition(**p) for p in positions if p['positionSide'] == 'SHORT'), None)

        return position_long, position_short

    return None, None


# @task
def get_order_id(symbol, order_id):
    order = client.query_order(symbol=symbol, orderId=order_id)
    return order


# @task
def check_all_orders(symbol: str, orderId: int = None):
    """
    Monitor all  orders.

    :param symbol: The symbol of the order to monitor.
    :return: The order status.
    """
    orders = client.get_all_orders(symbol=symbol, orderId=orderId)

    if orders:
        logging.info(f"Orders: {orders}")
        return orders
    else:
        logging.info(f"No orders found")
        return None


# @task
def get_last_order_in_position(symbol: str):
    """
    Monitor all  orders.

    :param symbol: The symbol of the order to monitor.
    :return: The order status.
    """
    orders = client.get_all_orders(symbol=symbol)

    if orders:
        logging.info(f"Orders: {orders}")
        return orders
    else:
        logging.info(f"No orders found")
        return None


# @task
def get_current_price(symbol: str) -> Decimal:
    try:
        ticker = client.ticker_price(symbol)
        return Decimal(ticker.get('price'))
    except Exception as e:
        logging.error(f"Failed to get current price: {e}")
        raise HTTPException(status_code=500, detail="Failed to get current price")


# @task
def cancel_open_orders(symbol: str) -> dict:
    status = client.cancel_open_orders(symbol=symbol)
    print(f">>> Cancel all open orders: {status}")
    return status


# @task
def get_position_closed_pnl(symbol: str) -> Decimal:
    # orders = client.get_account_trades(symbol=symbol, orderId=order_id)
    orders = client.get_account_trades(symbol=symbol, limit=1)[::-1]
    return Decimal(orders[0].get('realizedPnl'))
