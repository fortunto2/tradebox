import logging

from sqlalchemy import func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from core.binance_futures import create_order_binance, monitor_ws, client
from core.db_async import get_async_session, async_engine
from core.models.orders import Order, OrderStatus, OrderType
import asyncio


async def load_new_orders(session: AsyncSession, symbol: str = None):
    """
    Load all orders from db by symbol and status NEW
    :param status:
    :param session: The async session to use for the query
    :param symbol: The symbol of the order to monitor
    :return: The order status
    """
    status: OrderStatus = OrderStatus.NEW

    subquery_in_progress = (
        select(Order.symbol)
        .where(Order.status == OrderStatus.IN_PROGRESS.value)
        .group_by(Order.symbol)
        .subquery()
    )

    if symbol:
        # If a specific symbol is provided, get the order with the highest order_number for that symbol
        subquery = (
            select(Order.symbol, func.min(Order.order_number).label("min_order_number"))
            .where(Order.symbol == symbol, Order.status == status.value)
            .group_by(Order.symbol)
            .subquery()
        )
    else:
        # If no specific symbol is provided, get the orders with the highest order_number for each symbol
        subquery = (
            select(Order.symbol, func.min(Order.order_number).label("min_order_number"))
            .where(Order.status == status.value)
            .group_by(Order.symbol)
            .subquery()
        )

    query = (
        select(Order)
        .join(subquery, (Order.symbol == subquery.c.symbol) & (Order.order_number == subquery.c.min_order_number))
        .outerjoin(subquery_in_progress, Order.symbol == subquery_in_progress.c.symbol)
        .where(subquery_in_progress.c.symbol == None)
        # Exclude orders if any order in the group has the status IN_PROGRESS
    )

    result = await session.exec(query)
    return result.all()


async def create_new_orders():
    """
    #1 get from db all list model Order by symbol and new
    #2 create create_order_binance
    #3 wait websocket by monitor_ws
    :return:
    """

    async with AsyncSession(async_engine) as session:
        async with session.begin():
            orders = await load_new_orders(session)
            if orders:
                # todo: перероверять статусы на бинанс
                order = orders[0]
                print(f'Create new orders for {order.symbol}')
                order_id_binance = await create_order_binance(order)
                # Add the websocket monitoring code here if necessary

                # save order_id_binance to db
                order.binance_id = order_id_binance
                order.status = OrderStatus.IN_PROGRESS

                session.add(order)
                await session.commit()


logging.basicConfig(level=logging.INFO)

# Глобальная очередь для новых ордеров
new_orders_queue = asyncio.Queue()


async def load_in_progress_orders(session: AsyncSession):
    """
    Load all orders with status IN_PROGRESS from the database.
    """
    query = select(Order).where(Order.status == OrderStatus.IN_PROGRESS)
    result = await session.exec(query)
    return result.all()


async def db_get_last_order(webhook_id, session: AsyncSession, order_type=OrderType.MARKET):
    """
    Load all orders with status webhook, status Filled, Market type.
    """
    query = select(Order).where(
        Order.webhook_id == webhook_id,
        Order.status == OrderStatus.FILLED,
        Order.type == order_type
    ).order_by(Order.id.desc())

    result = await session.exec(query)
    return result.first()


async def db_get_all_order(
        webhook_id,
        order_status: OrderStatus,
        order_type: OrderType,
        session: AsyncSession,
):
    """
    Load all orders by webhook
    """
    query = select(Order).where(
        Order.webhook_id == webhook_id,
        Order.status == order_status,
        Order.type == order_type
    ).order_by(Order.id.desc())

    result = await session.exec(query)
    return result.all()


def on_message(ws, msg, session):
    logging.info(f"Received message: {msg}")
    if msg['e'] == 'ORDER_TRADE_UPDATE':
        order_status = msg['o']['X']
        logging.info(f"Order status: {order_status}")
        if order_status in ['FILLED', 'CANCELED', 'REJECTED']:
            logging.info(f"Order completed with status: {order_status}")
            # Update the order status in the database
            asyncio.create_task(update_order_status(msg, session))


async def update_order_status(msg, session: AsyncSession):
    """
    Update the order status in the database based on the message received from the websocket.
    """
    order_id = msg['o']['i']
    order_status = msg['o']['X']

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
                    await new_orders_queue.put(next_order.symbol)


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


async def monitor_symbol(symbol: str, session: AsyncSession):
    """
    Monitor a given symbol using websocket.
    """
    from binance.websocket.um_futures.websocket_client import UMFuturesWebsocketClient

    listen_key = client.new_listen_key().get('listenKey')
    ws_client = UMFuturesWebsocketClient(lambda ws, msg: on_message(ws, msg, session))
    ws_client.user_data(listen_key=listen_key, symbol=symbol)


async def monitor_orders():
    """
    Monitor orders and update their status based on websocket messages.
    """
    async with AsyncSession(async_engine) as session:
        orders = await load_in_progress_orders(session)

        # Start websocket monitoring for each symbol
        tasks = {order.symbol: asyncio.create_task(monitor_symbol(order.symbol, session)) for order in orders}

        # Continuously check for new orders from the queue and start monitoring them
        while True:
            symbol = await new_orders_queue.get()
            if symbol not in tasks:
                tasks[symbol] = asyncio.create_task(monitor_symbol(symbol, session))
            new_orders_queue.task_done()


async def create_order_and_monitor(session: AsyncSession, order):
    """
    Create a new order in Binance and start monitoring it.
    """
    await create_order_binance(order)
    await new_orders_queue.put(order.symbol)


if __name__ == '__main__':
    import asyncio

    loop = asyncio.get_event_loop()
    if loop.is_running():
        asyncio.run(create_new_orders())
    else:
        loop.run_until_complete(create_new_orders())
