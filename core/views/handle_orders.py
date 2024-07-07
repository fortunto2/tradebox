import logging

from sqlalchemy import func
from sqlalchemy.orm import joinedload
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from core.db_async import async_engine
from core.models.orders import Order, OrderStatus, OrderType, OrderPositionSide, OrderSide

from core.models.webhook import WebHook
from core.schemas.webhook import WebhookPayload


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


async def load_in_progress_orders(session: AsyncSession):
    """
    Load all orders with status IN_PROGRESS from the database.
    """
    query = select(Order).where(Order.status == OrderStatus.IN_PROGRESS)
    result = await session.exec(query)
    return result.all()


async def get_webhook(webhook_id: str, session: AsyncSession) -> WebHook:
    query = select(WebHook).where(WebHook.id == webhook_id)
    result = await session.exec(query)
    return result.first()


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


async def db_get_orders(
        webhook_id,
        order_status: OrderStatus,
        position_side: OrderPositionSide,
        order_type: OrderType,
        order_side: OrderSide,
        session: AsyncSession,
):
    """
    Load all orders grid
    """
    query = select(Order).where(
        Order.webhook_id == webhook_id,
        Order.status == order_status,
        Order.type == order_type,
        Order.position_side == position_side,
        Order.side == order_side
    ).order_by(Order.id.asc())

    result = await session.exec(query)
    return result.all()


async def db_get_order(
        order_id,
        session: AsyncSession
) -> Order:
    query = select(Order).where(
        Order.id == order_id,
    )

    result = await session.exec(query)
    return result.one_or_none()


async def db_get_order_binance_id(
        order_binance_id,
        session: AsyncSession
) -> Order:
    query = select(Order).options(joinedload(Order.webhook)).where(Order.binance_id == order_binance_id)

    result = await session.exec(query)
    return result.unique().one()


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


async def main():

    async with AsyncSession(async_engine) as session:
        order = await db_get_order_binance_id(1594495326, session)
        webhook = order.webhook

        payload = WebhookPayload(
            name=webhook.name,
            side=order.side,
            positionSide=order.position_side,
            symbol=order.symbol,
            open=webhook.open,
            settings=webhook.settings
        )

        print(payload.model_dump())


if __name__ == "__main__":

    import asyncio

    asyncio.run(main())
