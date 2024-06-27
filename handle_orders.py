from sqlalchemy import func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from core.binance_futures import create_order_binance, monitor_ws
from core.db_async import get_async_session, async_engine
from core.models.orders import Order, OrderStatus


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
        .where(subquery_in_progress.c.symbol == None)  # Exclude orders if any order in the group has the status IN_PROGRESS
    )

    result = await session.exec(query)
    return result.all()


async def load_in_progres_orders(session: AsyncSession, symbol: str = None):
    """
    Load all orders from db by symbol and status IN_PROGRESS
    :param status:
    :param session: The async session to use for the query
    :param symbol: The symbol of the order to monitor
    :return: The order status
    """
    status: OrderStatus = OrderStatus.IN_PROGRESS

    query = (
        select(Order)
        .where(Order.status == status.value)
    )
    if symbol:
        query = query.where(Order.symbol == symbol)

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
                order_id_binance = await create_order_binance(order)
                # Add the websocket monitoring code here if necessary

                # save order_id_binance to db
                order.binance_id = order_id_binance
                order.status = OrderStatus.IN_PROGRESS

                session.add(order)
                await session.commit()


async def wait_order_status():
    """
    #1 get from db all list model Order by symbol and in_progress
    #2 wait websocket by monitor_ws
    :return:
    """
    async with AsyncSession(async_engine) as session:
        async with session.begin():

            orders = await load_in_progres_orders(session)

            for order in orders:
                monitor_ws(order)


if __name__ == '__main__':
    import asyncio

    loop = asyncio.get_event_loop()
    if loop.is_running():
        asyncio.run(wait_order_status())
    else:
        loop.run_until_complete(wait_order_status())
