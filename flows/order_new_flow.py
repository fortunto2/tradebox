from prefect import flow, get_run_logger
from prefect.task_runners import ConcurrentTaskRunner

from core.clients.db_sync import SessionLocal
from core.logger import logger
from core.models.orders import OrderStatus, Order, OrderType, OrderPositionSide, OrderSide
from core.schemas.events.order_trade_update import OrderTradeUpdate
from core.views.handle_orders import db_get_order_binance_id, get_webhook_last, db_set_order_status


@flow(task_runner=ConcurrentTaskRunner())
def order_new_flow(event: OrderTradeUpdate):

    logger.info(f"Order status: {event.order_status}")
    order_binance_id = str(event.order_id)
    logger.info(f"Order binance_id: {order_binance_id}")

    webhook = get_webhook_last(event.symbol)

    # LONG_LIMIT = "LONG_LIMIT"
    # LONG_MARKET = "LONG_MARKET"
    # SHORT_MARKET = "SHORT_MARKET"
    # LONG_TAKE_PROFIT = "LONG_TAKE_PROFIT"
    # # our custom
    # SHORT_LIMIT = "SHORT_LIMIT"
    # SHORT_STOP_LOSS = "SHORT_STOP_LOSS"

    # choise from OrderType by event
    if event.position_side == 'SHORT' and event.side == 'SELL' and event.order_type == 'STOP':
        type_order = OrderType.SHORT_LIMIT
    elif event.position_side == 'SHORT' and event.side == 'BUY' and event.order_type == 'STOP':
        type_order = OrderType.SHORT_STOP_LOSS
    else:
        return

    with SessionLocal() as session:

        order: Order = Order(
            position_side=event.position_side,
            side=event.side,
            type=type_order,
            symbol=event.symbol,
            price=event.original_price,
            price_stop=event.stop_price,
            quantity=event.original_quantity,
            webhook_id=webhook.id,
            leverage=webhook.open['leverage'],
            status=OrderStatus.IN_PROGRESS,
            binance_status=event.order_status,
            binance_id=order_binance_id,
        )

        session.add(order)
        session.commit()

