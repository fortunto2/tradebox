from prefect import task, flow, tags
from prefect.task_runners import ConcurrentTaskRunner
from core.logger import logger
from flows.positions_flow import close_positions
from core.clients.db_sync import SessionLocal
from core.models.orders import OrderStatus, Order, OrderType, OrderSide
from core.schemas.events.order_trade_update import OrderTradeUpdate
from core.schemas.webhook import WebhookPayload
from core.views.handle_orders import db_get_order_binance_id
from flows.tasks.orders_create import create_short_market_stop_loss_order, create_long_tp_order
from flows.tasks.orders_processing import grid_make_long_limit_order, check_orders_in_the_grid
from flows.tasks.positions_processing import open_short_position_loop
from flows.order_new_flow import order_new_flow


@task(
    name='handle_order_update',
    task_run_name='handle_{event.symbol}_{event.order_type}',
    retries=3,
    retry_delay_seconds=5,
)
def handle_order_update(event):
    # Функция для обработки обновлений ордера
    pass


@flow(task_runner=ConcurrentTaskRunner())
async def order_filled_flow(event: OrderTradeUpdate, order_type: OrderType = None):
    with tags(event.symbol, event.order_type, event.order_status, event.position_side, event.side):
        with SessionLocal() as session:

            logger.info(f"Order status: {event.order_status}")
            order_binance_id = str(event.order_id)
            logger.info(f"Order binance_id: {order_binance_id}")

            order: Order = db_get_order_binance_id(order_binance_id)
            if not order:
                logger.warning(f"Order not found in DB - {order_binance_id}")
                if order_type:
                    await order_new_flow(event, order_type)
                return None
            elif order.status == OrderStatus.FILLED:
                logger.warning(f"Order already filled - {order_binance_id}")
                return None

            webhook = order.webhook
            webhook_id = order.webhook.id

            position = order.binance_position

            # if not order.binance_position_id:
            #     binance_position = get_exist_position(
            #         event.symbol,
            #         webhook.id,
            #         OrderPositionSide(event.position_side),
            #         check_closed=False
            #     )
            #     if not binance_position:
            #         logger.error(f"Position not found in DB - {event.symbol}")
            #     else:
            #         order.binance_position = binance_position

            order.binance_id = order_binance_id
            order.status = OrderStatus.FILLED
            order.binance_status = event.order_status
            order.price = event.average_price

            order.commission_asset = event.commission_asset
            order.commission = event.commission

            session.merge(order)
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
                logger.warning(f">> Close positions {event.symbol} by LONG_TAKE_PROFIT")
                await close_positions(
                    symbol=event.symbol,
                    close_long=False,
                    close_short=True
                )
            elif order.type == OrderType.SHORT_MARKET:
                pass
            elif order.type == OrderType.LONG_MARKET and order.side == OrderSide.BUY:
                # только первый раз в начале вебхука создаем ордеры
                tp_order = await create_long_tp_order.submit(
                    symbol=event.symbol,
                    tp=payload.settings.tp,
                    leverage=payload.open.leverage,
                    webhook_id=webhook_id,
                )

                # первый запуск создание пары ордеров лимитных по сетке
                await grid_make_long_limit_order.submit(
                    webhook_id=webhook_id,
                    payload=payload,
                )

            elif order.type == OrderType.LONG_LIMIT:
                logger.info(f"Order {order_binance_id} LIMIT start grid_make_limit_and_tp_order")
                tp_order = await create_long_tp_order.submit(
                    symbol=event.symbol,
                    tp=payload.settings.tp,
                    leverage=payload.open.leverage,
                    webhook_id=webhook_id
                )
                filled_orders_in_db, grid_orders, grid = await check_orders_in_the_grid(
                    payload, webhook_id)
                if len(grid) > len(filled_orders_in_db):
                    await grid_make_long_limit_order.submit(
                        webhook_id=webhook_id,
                        payload=payload
                    )
                else:
                    logger.info(f"stop: filled_orders {len(grid)} <= grid_orders {len(filled_orders_in_db)}")

            elif order.type == OrderType.SHORT_MARKET_STOP_LOSS:
                logger.info(f"Order {order_binance_id} SHORT_MARKET_STOP_LOSS start make_hedge_by_pnl")
                await open_short_position_loop(
                    payload=payload,
                    webhook_id=order.webhook_id,
                    order_binance_id=order_binance_id,
                )
            elif order.type in {OrderType.SHORT_LIMIT, OrderType.SHORT_MARKET_STOP_OPEN}:
                short_stop_loss_order = await create_short_market_stop_loss_order(
                    symbol=payload.symbol,
                    sl_short=payload.settings.sl_short,
                    leverage=payload.open.leverage,
                    webhook_id=order.webhook_id,
                    position_short=position,
                    price_original=event.original_price
                )
                logger.info(f"Create short_stop_loss_order: {short_stop_loss_order.id}")

