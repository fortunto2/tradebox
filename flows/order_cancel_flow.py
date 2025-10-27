from prefect import flow, tags
from prefect.task_runners import ConcurrentTaskRunner
from core.logger import logger
from core.models.orders import OrderStatus, Order
from core.schemas.events.order_trade_update import OrderTradeUpdate
from core.views.handle_orders import db_set_order_status


@flow(task_runner=ConcurrentTaskRunner())
async def order_cancel_flow(event: OrderTradeUpdate):
    # with tags(event.symbol, event.order_type, event.order_status, event.position_side, event.side):

        logger.info(f"Order status: {event.order_status}")
        order_binance_id = str(event.order_id)
        logger.info(f"Order binance_id: {order_binance_id}")

        order = await db_set_order_status.submit(
            order_binance_id=order_binance_id,
            status=OrderStatus.CANCELED,
            binance_status=event.order_status,
        )

        # if order.result():
        #     logger.info(f"Order {order_binance_id} status set to CANCELED")
        # else:
        #     logger.warning(f"Order {order_binance_id} was not found or could not be updated")
