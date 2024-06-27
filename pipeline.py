import asyncio
import logging
from functools import partial

from binance.websocket.um_futures.websocket_client import UMFuturesWebsocketClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from core.models.orders import Order, OrderStatus
from core.db_async import async_engine
from core.binance_futures import create_order_binance, client
from prefect import flow, task, get_run_logger

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

message_queue = asyncio.Queue()


@task(retries=3, retry_delay_seconds=10)
async def load_in_progress_orders():
    """
    Load all orders with status IN_PROGRESS from the database.
    """
    async with AsyncSession(async_engine) as session:
        query = select(Order).where(Order.status == OrderStatus.IN_PROGRESS)
        result = await session.exec(query)
        return result.all()


async def on_message(ws, msg):
    logger.info(f"Received message: {msg}")
    await message_queue.put(msg)

@task(retries=3, retry_delay_seconds=10)
async def process_messages():
    while True:
        if not message_queue.empty():
            msg = message_queue.get()
            if msg['e'] == 'ORDER_TRADE_UPDATE':
                order_status = msg['o']['X']
                logger.info(f"Order status: {order_status}")
                if order_status in ['FILLED', 'CANCELED', 'REJECTED']:
                    logger.info(f"Order completed with status: {order_status}")
                    await update_order_status(msg)
        await asyncio.sleep(0.1)  # Небольшая пауза, чтобы не нагружать процессор


@task(retries=3, retry_delay_seconds=10)
async def update_order_status(msg):
    """
    Update the order status in the database based on the message received from the websocket.
    """
    order_id = msg['o']['i']
    order_status = msg['o']['X']

    async with AsyncSession(async_engine) as session:
        async with session.begin():
            order = await session.get(Order, order_id)
            if order:
                order.status = OrderStatus(order_status)
                await session.commit()

                # If the order is completed, create a new order if available
                if order_status == OrderStatus.FILLED:
                    next_order = await get_next_order(session, order.symbol)
                    if next_order:
                        await create_order_binance(next_order)
                        await monitor_symbol.submit(next_order.symbol)


@task(retries=3, retry_delay_seconds=10)
async def get_next_order(session: AsyncSession, symbol: str):
    """
    Get the next order for a given symbol that is not yet processed.
    """
    query = select(Order).where(Order.symbol == symbol, Order.status == OrderStatus.NEW).order_by(Order.order_number)
    result = await session.exec(query)
    next_order = result.first()
    if next_order:
        next_order.status = OrderStatus.IN_PROGRESS
        await session.commit()
    return next_order


@task(retries=3, retry_delay_seconds=10, timeout_seconds=3600)
async def monitor_symbol(symbol: str):
    """
    Monitor a given symbol using websocket.
    """
    listen_key = client.new_listen_key().get('listenKey')

    ws_client = UMFuturesWebsocketClient(on_message=on_message)

    try:
        ws_client.user_data(
            listen_key=listen_key,
            id=1
        )

        # Keep the connection alive
        while True:
            await asyncio.sleep(60)
            # Refresh listen key every 30 minutes
            if (asyncio.get_event_loop().time() % 1800) < 60:
                client.renew_listen_key(listen_key)

            # Ping to keep the connection alive
            ws_client.ping()

    except Exception as e:
        logger.error(f"Error in websocket connection: {e}")
    finally:
        ws_client.stop()


@task(retries=3, retry_delay_seconds=10)
async def create_order_and_monitor(order):
    """
    Create a new order in Binance and start monitoring it.
    """
    await create_order_binance(order)
    await monitor_symbol.submit(order.symbol)


@flow
async def main_flow():
    in_progress_orders = await load_in_progress_orders()

    # Запускаем задачу обработки сообщений
    process_task = asyncio.create_task(process_messages())

    # Запускаем мониторинг для каждого символа
    monitor_tasks = [monitor_symbol.submit(order.symbol) for order in in_progress_orders]

    # Ждем завершения всех задач
    await asyncio.gather(process_task, *monitor_tasks)


if __name__ == '__main__':

    asyncio.run(main_flow())
