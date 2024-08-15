from datetime import timedelta
import logging
from fastapi import HTTPException
from prefect import task, tags
from prefect.tasks import task_input_hash
from sqlmodel import select
from binance.client import AsyncClient
from binance.enums import *
from decimal import Decimal, ROUND_DOWN
import asyncio

from core.clients.db_sync import SessionLocal, execute_sqlmodel_query_single
from core.models.binance_symbol import BinanceSymbol
from core.schemas.position import LongPosition, ShortPosition
from core.models.orders import Order, OrderType
from config import settings

client = None

async def init_client():
    global client
    if client is None:
        client = await AsyncClient.create(settings.BINANCE_API_KEY, settings.BINANCE_API_SECRET)


async def close_client():
    global client
    if client is not None:
        await client.close_connection()
        client = None


@task(cache_key_fn=task_input_hash, cache_expiration=timedelta(days=1))
async def get_symbol_info(symbol):
    await init_client()
    exchange_info = await client.futures_exchange_info()
    for s in exchange_info['symbols']:
        if s['symbol'] == symbol:
            return s
    return None


def adjust_precision(value, precision):
    quantize_str = '1.' + '0' * precision if precision > 0 else '1'
    return value.quantize(Decimal(quantize_str), rounding=ROUND_DOWN)


async def get_symbol_quantity_and_precisions(symbol):
    await init_client()

    def query_func(session_local):
        query = select(BinanceSymbol).where(BinanceSymbol.symbol == symbol)
        result = session_local.exec(query)
        return result.first()

    bs = execute_sqlmodel_query_single(query_func)
    if not bs:
        symbol_info = await get_symbol_info(symbol)
        if not symbol_info:
            raise ValueError(f"Symbol {symbol} not found in exchange info")

        quantity_precision = 0
        price_precision = 8

        for filter in symbol_info['filters']:
            if filter['filterType'] == 'LOT_SIZE':
                quantity_precision = int(filter['stepSize'].find('1') - 1)
            if filter['filterType'] == 'PRICE_FILTER':
                price_precision = int(filter['tickSize'].find('1') - 1)

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

async def get_symbol_price_and_quantity_by_precisions(symbol, quantity, price=None):
    await init_client()
    quantity_precision, price_precision = await get_symbol_quantity_and_precisions(symbol)

    if price is None:
        ticker = await client.futures_symbol_ticker(symbol=symbol)
        price = ticker.get('price')

    quantity = adjust_precision(Decimal(quantity), quantity_precision)
    price = adjust_precision(Decimal(price), price_precision)

    return quantity, price

@task(name=f'create_order_binance', task_run_name='create_order_{order.side.value}_{order.type.value}')
async def create_order_binance(order: Order, return_full_response=False):
    with tags(order.symbol, order.side.value, order.type.value, order.position_side.value):
        quantity, price = await get_symbol_price_and_quantity_by_precisions(order.symbol, order.quantity, order.price)

        order_params = {
            "symbol": order.symbol,
            "type": order.type.value,
            "quantity": quantity,
            "positionSide": order.position_side.value,
            "side": order.side.value,
            'newClientOrderId': order.id,
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
        else:
            order_params["price"] = price
            order_params["timeInForce"] = "GTC"
            order_params["type"] = 'LIMIT'

        response = await client.futures_create_order(**order_params)

        logging.info(f"Order created successfully: {response}")
        if return_full_response:
            return response
        return str(response['orderId'])


@task
async def cancel_order_binance(symbol, order_id):
    await init_client()
    response = await client.futures_cancel_order(symbol=symbol, orderId=order_id)
    logging.info(f"Order canceled successfully: {response}")
    return response


async def check_position_side_dual() -> bool:
    await init_client()
    try:
        dual_side_position = await client.futures_get_position_mode()

        if dual_side_position['dualSidePosition']:
            logging.info(f"Position side dual: {dual_side_position}")
            return True
        else:
            logging.info(f"No position side dual found")
            r = await client.futures_change_position_mode(dualSidePosition=True)

            if r['code'] == 200:
                logging.info(f"Position side dual changed to True")
            else:
                logging.error(f"Failed to change position mode: {r}")
                return False

            await asyncio.sleep(1)
            dual_side_position = await client.futures_get_position_mode()
            logging.info(f"Position side dual: {dual_side_position}")

            return True

    except Exception as e:
        logging.error(f"Failed to get position side dual: {e}")
        raise HTTPException(status_code=500, detail="Failed to get position side dual")


async def check_position(symbol: str):
    await init_client()
    positions = await client.futures_position_information(symbol=symbol)
    if positions:
        logging.info(f"Position: {positions}")

        position_long = next((LongPosition(**p) for p in positions if p['positionSide'] == 'LONG'), None)
        position_short = next((ShortPosition(**p) for p in positions if p['positionSide'] == 'SHORT'), None)

        return position_long, position_short

    return None, None


@task
async def get_order_id(symbol, order_id):
    await init_client()
    order = await client.futures_get_order(symbol=symbol, orderId=order_id)
    return order


@task
async def check_all_orders(symbol: str, orderId: int = None):
    """
    Monitor all  orders.

    :param symbol: The symbol of the order to monitor.
    :return: The order status.
    """
    await init_client()
    orders = await client.futures_get_all_orders(symbol=symbol, orderId=orderId)

    if orders:
        logging.info(f"Orders: {orders}")
        return orders
    else:
        logging.info(f"No orders found")
        return None


@task
async def get_current_price(symbol: str) -> Decimal:
    await init_client()
    try:
        ticker = await client.futures_symbol_ticker(symbol=symbol)
        return Decimal(ticker.get('price'))
    except Exception as e:
        logging.error(f"Failed to get current price: {e}")
        raise HTTPException(status_code=500, detail="Failed to get current price")


@task
async def cancel_open_orders(symbol: str) -> dict:
    await init_client()
    status = await client.futures_cancel_all_open_orders(symbol=symbol)
    logging.info(f"Cancel all open orders: {status}")
    return status


@task
async def get_position_closed_pnl(symbol: str, order_id: int) -> Decimal:
    await init_client()
    orders = await client.futures_account_trades(symbol=symbol, orderId=order_id)
    return Decimal(orders[0].get('realizedPnl'))
