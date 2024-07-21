from time import sleep
from prefect import task, flow, tags
from prefect import flow, get_run_logger
from prefect.task_runners import ConcurrentTaskRunner

from core.logger import logger
from core.models.monitor import SymbolPosition
from flows.tasks.binance_futures import cancel_open_orders
from core.clients.db_sync import SessionLocal
from core.models.orders import OrderStatus, Order, OrderType
from core.schemas.events.order_trade_update import OrderTradeUpdate
from core.schemas.webhook import WebhookPayload
from core.views.handle_orders import db_get_order_binance_id, get_webhook_last
from flows.tasks.orders_create import create_short_stop_loss_order, create_long_tp_order
from flows.tasks.orders_processing import open_short_position_loop, grid_make_long_limit_order, check_orders_in_the_grid


@task(
    name=f'handle_order_update',
    task_run_name='handle_{event.symbol}_{event.order_type}',
    retries=3,
    retry_delay_seconds=5,
)
def handle_order_update(event):
    pass


@flow(task_runner=ConcurrentTaskRunner())
def order_filled_flow(event: OrderTradeUpdate, position: SymbolPosition):
    with tags(event.symbol, event.order_type, event.order_status, event.position_side, event.side):
        with SessionLocal() as session:

            logger.info(f"Order status: {event.order_status}")
            order_binance_id = str(event.order_id)
            logger.info(f"Order binance_id: {order_binance_id}")

            order: Order = db_get_order_binance_id(order_binance_id)
            webhook = order.webhook
            webhook_id = order.webhook.id

            # webhook = get_webhook_last(event.symbol)
            # if not webhook:
            #     logger.error(f"!!!!!Webhook not found in DB - {event.symbol}")
            #     return None

            order.binance_id = order_binance_id
            order.status = OrderStatus.FILLED
            order.binance_status = event.order_status
            order.price = event.average_price

            session.add(order)
            session.commit()

            payload = WebhookPayload(
                name=webhook.name,
                side=order.side,
                positionSide=order.position_side,
                symbol=order.symbol,
                open=webhook.open,
                settings=webhook.settings
            )

            if order.type == OrderType.LONG_TAKE_PROFIT:
                status_cancel = cancel_open_orders(symbol=order.symbol)

            elif order.type == OrderType.LONG_LIMIT:
                logger.info(f"Order {order_binance_id} LIMIT start grid_make_limit_and_tp_order")
                tp_order = create_long_tp_order.submit(
                    symbol=payload.symbol,
                    tp=payload.settings.tp,
                    leverage=payload.open.leverage,
                    webhook_id=webhook_id,
                    position=position
                )
                filled_orders_in_db, grid_orders, grid = check_orders_in_the_grid(
                    payload, webhook_id)
                if len(grid) > len(filled_orders_in_db):

                    grid_make_long_limit_order.submit(
                        webhook_id=webhook_id,
                        payload=payload
                    )
                else:
                    logger.info(f"stop: filled_orders {len(grid)} <= grid_orders {len(filled_orders_in_db)}")


            elif order.type == OrderType.SHORT_STOP_LOSS:
                logger.info(f"Order {order_binance_id} HEDGE_STOP_LOSS start make_hedge_by_pnl")
                open_short_position_loop.submit(
                    payload=payload,
                    webhook_id=order.webhook_id,
                    order_binance_id=order_binance_id,
                )
            elif order.type == OrderType.SHORT_LIMIT:
                short_stop_loss_order = create_short_stop_loss_order.submit(
                    symbol=payload.symbol,
                    sl_short=payload.settings.sl_short,
                    leverage=payload.open.leverage,
                    webhook_id=order.webhook_id,
                    position=position,
                    price_original=event.original_price
                )
                logger.info(f"Create short_stop_loss_order: {short_stop_loss_order.id}")

        session.commit()

