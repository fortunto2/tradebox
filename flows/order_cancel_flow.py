from time import sleep
from prefect import task, flow, tags
from prefect import flow, get_run_logger
from prefect.task_runners import ConcurrentTaskRunner

from core.clients.db_sync import SessionLocal
from core.logger import logger
from core.models.orders import OrderStatus, Order, OrderType
from core.schemas.events.order_trade_update import OrderTradeUpdate
from core.schemas.webhook import WebhookPayload
from core.views.handle_orders import db_get_order_binance_id, get_webhook_last, db_set_order_status



@flow(task_runner=ConcurrentTaskRunner(), log_prints=True)
def order_cancel_flow(event: OrderTradeUpdate):

    # with SessionLocal() as session:

    logger.info(f"Order status: {event.order_status}")
    order_binance_id = str(event.order_id)
    logger.info(f"Order binance_id: {order_binance_id}")

    order: Order = db_set_order_status(
        order_binance_id=order_binance_id,
        status=OrderStatus.CANCELED,
        binance_status=event.order_status,
    )

    # webhook = order.webhook
    # webhook_id = order.webhook.id
    #
    # payload = WebhookPayload(
    #     name=webhook.name,
    #     side=order.side,
    #     positionSide=order.position_side,
    #     symbol=order.symbol,
    #     open=webhook.open,
    #     settings=webhook.settings
    # )

    # if order.type == OrderType.LONG_TAKE_PROFIT:

