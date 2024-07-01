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

from handle_orders import load_new_orders

# Configuring the logging level and logger.
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global message queue for WebSocket messages.
message_queue = asyncio.Queue()


# Task to load new orders
@task
async def load_new_orders_task(session: AsyncSession, symbol: str = None):
    return await load_new_orders(session, symbol)


@task
async def create_and_monitor_new_orders():
    async with AsyncSession(async_engine) as session:
        async with session.begin():
            orders = await load_new_orders(session)
            if orders:
                # Assuming create_order_binance does not require an open session
                for order in orders:
                    order_id_binance = await create_order_binance(order)
                    order.binance_id = order_id_binance
                    order.status = OrderStatus.IN_PROGRESS
                    session.add(order)
                await session.commit()  # Commit all changes at once

        # After the session is committed and closed, start monitoring
        for order in orders:
            await monitor_symbol.submit(order.symbol)  # This should be outside the session scope if it does not need database access


@task(retries=3, retry_delay_seconds=10)
async def load_in_progress_orders():
    """Load all orders with status IN_PROGRESS from the database."""
    async with AsyncSession(async_engine) as session:
        result = await session.exec(select(Order).where(Order.status == OrderStatus.IN_PROGRESS))
        return result.all()


def on_message(ws, msg):
    """Log and queue messages from the WebSocket."""
    logger.info(f"Received message: {msg}")
    message_queue.put_nowait(msg)


@task(retries=3, retry_delay_seconds=10)
async def process_messages():
    """Process messages from the queue, updating order statuses as needed."""
    while True:
        msg = await message_queue.get()
        if msg['e'] == 'ORDER_TRADE_UPDATE':
            await handle_order_update(msg)
        await asyncio.sleep(0.1)


async def handle_order_update(msg):
    """Handle order update from messages, log and update status."""
    order_status = msg['o']['X']
    logger.info(f"Order status: {order_status}")
    if order_status in ['FILLED', 'CANCELED', 'REJECTED']:
        logger.info(f"Order completed with status: {order_status}")
        await update_order_status(msg)


@task(retries=3, retry_delay_seconds=10)
async def update_order_status(msg):
    """Update the order status in the database."""
    async with AsyncSession(async_engine) as session, session.begin():
        order = await session.get(Order, msg['o']['i'])
        if order:
            order.status = OrderStatus(msg['o']['X'])
            await session.commit()
            if order.status == OrderStatus.FILLED:
                await handle_filled_order(session, order)


async def handle_filled_order(session, order):
    """Create a new order if the previous one is filled."""
    next_order = await get_next_order(session, order.symbol)
    if next_order:
        await create_order_binance(next_order)
        await monitor_symbol.submit(next_order.symbol)


@task(retries=3, retry_delay_seconds=10)
async def get_next_order(session: AsyncSession, symbol: str):
    """Get the next order for a symbol, mark as IN_PROGRESS."""
    result = await session.exec(
        select(Order).where(Order.symbol == symbol, Order.status == OrderStatus.NEW).order_by(Order.order_number))
    next_order = result.first()
    if next_order:
        next_order.status = OrderStatus.IN_PROGRESS
        await session.commit()
    return next_order


@task(retries=3, retry_delay_seconds=10, timeout_seconds=3600)
async def monitor_symbol(symbol: str):
    """Monitor a symbol using WebSocket, maintain the listen key."""
    listen_key = client.new_listen_key().get('listenKey')
    ws_client = UMFuturesWebsocketClient(on_message=on_message)
    try:
        ws_client.user_data(listen_key=listen_key, id=1)
        while True:
            await asyncio.sleep(60)
            client.renew_listen_key(listen_key) if (asyncio.get_event_loop().time() % 1800) < 60 else None
            ws_client.ping()
    except Exception as e:
        logger.error(f"Error in websocket connection: {e}")
    finally:
        ws_client.stop()


# Main flow to process and monitor orders
@flow
async def main_flow():
    logger.info("Starting the main flow to process and monitor orders.")
    in_progress_orders = await load_in_progress_orders()
    new_order_creation_task = asyncio.create_task(create_and_monitor_new_orders())

    process_task = asyncio.create_task(process_messages())
    monitor_tasks = [monitor_symbol.submit(order.symbol) for order in in_progress_orders]

    await asyncio.gather(new_order_creation_task, process_task, *monitor_tasks)


if __name__ == '__main__':
    asyncio.run(main_flow())
