import logging

from prefect import task
from sqlalchemy import func
from sqlalchemy.orm import joinedload
from sqlmodel import select
from core.models.orders import Order, OrderStatus, OrderType, OrderPositionSide, OrderSide
from core.models.webhook import WebHook
from core.schemas.webhook import WebhookPayload
from core.clients.db_sync import execute_sqlmodel_query, execute_sqlmodel_query_single


def load_new_orders(symbol: str = None):
    """
    Load all orders from db by symbol and status NEW
    :param symbol: The symbol of the order to monitor
    :return: The order status
    """
    def query_func(session):
        status = OrderStatus.NEW

        subquery_in_progress = (
            select(Order.symbol)
            .where(Order.status == OrderStatus.IN_PROGRESS.value)
            .group_by(Order.symbol)
            .subquery()
        )

        if symbol:
            subquery = (
                select(Order.symbol, func.min(Order.order_number).label("min_order_number"))
                .where(Order.symbol == symbol, Order.status == status.value)
                .group_by(Order.symbol)
                .subquery()
            )
        else:
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
        )

        result = session.exec(query)
        return result.all()

    return execute_sqlmodel_query(query_func)


def load_in_progress_orders():
    """
    Load all orders with status IN_PROGRESS from the database.
    """
    def query_func(session):
        query = select(Order).where(Order.status == OrderStatus.IN_PROGRESS)
        result = session.exec(query)
        return result.all()

    return execute_sqlmodel_query(query_func)


def get_webhook(webhook_id: str) -> WebHook:
    def query_func(session):
        query = select(WebHook).where(WebHook.id == webhook_id)
        result = session.exec(query)
        return result.first()

    return execute_sqlmodel_query_single(query_func)


def get_webhook_last(symbol: str) -> WebHook:
    def query_func(session):
        query = select(WebHook).where(WebHook.symbol == symbol).order_by(WebHook.id.desc())
        result = session.exec(query)
        return result.first()

    return execute_sqlmodel_query_single(query_func)




def get_all_symbols(status=None) -> list:
    def query_func(session):
        if status is None:
            query = select(Order).group_by(Order.symbol)
        else:
            query = select(Order).where(Order.status == status).group_by(Order.symbol)
        result = session.exec(query)
        list_symbols = [order.symbol for order in result.all()]
        return list_symbols

    return execute_sqlmodel_query(query_func)


def db_get_last_order(webhook_id, order_type=OrderType.LONG_MARKET, order_by='desc') -> Order:
    def query_func(session):
        query = select(Order).where(
            Order.webhook_id == webhook_id,
            Order.status == OrderStatus.FILLED,
            Order.type == order_type
        )

        if order_by == 'desc':
            query = query.order_by(Order.id.desc())
        else:
            query = query.order_by(Order.id.asc())

        result = session.exec(query)
        return result.first()

    return execute_sqlmodel_query_single(query_func)


def db_get_orders(
        webhook_id,
        order_status: OrderStatus,
        position_side: OrderPositionSide,
        order_type: OrderType,
        order_side: OrderSide,
) -> list:
    def query_func(session):
        query = select(Order).where(
            Order.webhook_id == webhook_id,
            Order.status == order_status,
            Order.type == order_type,
            Order.position_side == position_side,
            Order.side == order_side
        ).order_by(Order.id.asc())

        result = session.exec(query)
        return result.all()

    return execute_sqlmodel_query(query_func)


def db_get_order(order_id) -> Order:
    def query_func(session):
        query = select(Order).where(Order.id == order_id)
        result = session.exec(query)
        return result.one_or_none()

    return execute_sqlmodel_query_single(query_func)


# @task(
#     name=f'set_order_status',
#     task_run_name='set_{order_binance_id}_status_{status.value}'
# )
def db_set_order_status(order_binance_id, status: OrderStatus, binance_status: str = None) -> Order:
    def query_func(session):
        query = select(Order).where(Order.binance_id == order_binance_id)
        order = session.exec(query).first()
        order.status = status
        if binance_status:
            order.binance_status = binance_status
        session.add(order)
        session.commit()
        return order

    return execute_sqlmodel_query_single(query_func)


# @task
def db_get_order_binance_id(order_binance_id) -> Order:
    def query_func(session):
        try:
            query = select(Order).options(joinedload(Order.webhook)).where(Order.binance_id == order_binance_id)
            result = session.exec(query)
            return result.first()
        except Exception as e:
            print(f"no order in db {order_binance_id}")
            logging.error(f"Error: {e}")
            return None

    return execute_sqlmodel_query_single(query_func)


def db_get_order_binance_position_id(binance_position_id) -> Order:
    def query_func(session):
        try:
            query = select(Order
                           ).options(joinedload(Order.webhook)
                                     ).where(Order.binance_position_id == binance_position_id).order_by(Order.id.desc())
            result = session.exec(query)
            return result.all()
        except Exception as e:
            print(f"no order in db by binance_postition_id {binance_position_id}")
            logging.error(f"Error: {e}")
            return None

    return execute_sqlmodel_query_single(query_func)


def db_get_all_order(webhook_id, order_status: OrderStatus, order_type: OrderType) -> list:
    def query_func(session):
        query = select(Order).where(
            Order.webhook_id == webhook_id,
            Order.status == order_status,
            Order.type == order_type
        ).order_by(Order.id.desc())

        result = session.exec(query)
        return result.all()

    return execute_sqlmodel_query(query_func)


def get_next_order(symbol: str) -> Order:
    def query_func(session):
        query = select(Order).where(Order.symbol == symbol, Order.status == OrderStatus.NEW).order_by(Order.order_number)
        result = session.exec(query)
        next_order = result.first()
        if next_order:
            next_order.status = OrderStatus.IN_PROGRESS
            session.commit()
        return next_order

    return execute_sqlmodel_query_single(query_func)


def main():
    # order = db_get_order_binance_id(1594495326)
    # webhook = order.webhook
    #
    # payload = WebhookPayload(
    #     name=webhook.name,
    #     side=order.side,
    #     positionSide=order.position_side,
    #     symbol=order.symbol,
    #     open=webhook.open,
    #     settings=webhook.settings
    # )
    #
    # print(payload.model_dump())

    order = db_get_last_order(
        webhook_id='4',
        order_type=OrderType.SHORT_MARKET_STOP_OPEN,
        order_by='desc'

    )

    return order


if __name__ == "__main__":
    main()
