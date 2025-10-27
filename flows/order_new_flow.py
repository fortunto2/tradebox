from asyncio import sleep
from decimal import Decimal

from prefect import flow, get_run_logger, tags

from core.clients.db_sync import SessionLocal
from core.logger import logger
from core.models.orders import OrderStatus, Order, OrderType, OrderPositionSide, OrderSide
from core.schemas.events.order_trade_update import OrderTradeUpdate
from core.schemas.position import LongPosition, ShortPosition
from core.views.handle_orders import db_get_order_binance_id, get_webhook_last
from core.views.handle_positions import get_exist_position, open_position_task
from flows.tasks.binance_futures import check_position


@flow()
async def order_new_flow(event: OrderTradeUpdate, order_type: OrderType):
    with (tags(event.symbol, event.order_type, event.order_status, event.position_side, event.side)):

        logger.info(f"Order status: {event.order_status}")
        order_binance_id = str(event.order_id)
        logger.info(f"Order binance_id: {order_binance_id}")

        with SessionLocal() as session:

            webhook = get_webhook_last(event.symbol)

            binance_position = get_exist_position(
                event.symbol,
                webhook.id,
                OrderPositionSide(event.position_side),
                not_closed=True  # todo: вернул обратно, тк второй раз не создается шорт позиция иначе
            )

            if event.order_type == 'MARKET':
                if (event.position_side == 'LONG' and event.side == 'SELL') or \
                        (event.position_side == 'SHORT' and event.side == 'BUY'):
                    # это надо для последних закрывающих ордеров, инача заново позицию создают

                    binance_position = get_exist_position(
                        event.symbol,
                        webhook.id,
                        OrderPositionSide(event.position_side),
                        not_closed=False
                    )

            if not binance_position:

                logger.warning(f"Position not found in DB - {event.symbol}")

                position_long, position_short = check_position(symbol=event.symbol)
                position_long: LongPosition
                position_short: ShortPosition

                if event.position_side == 'LONG':
                    position_side = OrderPositionSide.LONG
                    position = position_long
                else:
                    position_side = OrderPositionSide.SHORT
                    position = position_short

                binance_position_id = open_position_task(
                    symbol=event.symbol,
                    webhook_id=webhook.id,
                    position_side=position_side,
                    position_qty=position.positionAmt,
                    entry_price=position.entryPrice,
                    entry_break_price=position.breakEvenPrice,
                )
            else:
                binance_position_id = binance_position.id

            order: Order = db_get_order_binance_id(order_binance_id)
            if order:
                logger.warning(f"Order already exists in DB - {order_binance_id}")
                order.binance_position_id = binance_position_id
                order.webhook = webhook
                order.status = OrderStatus.IN_PROGRESS

            else:

                order: Order = Order(
                    position_side=event.position_side,
                    side=event.side,
                    type=order_type,
                    symbol=event.symbol,
                    price=event.original_price,
                    price_stop=event.stop_price,
                    quantity=event.original_quantity,
                    webhook_id=webhook.id,
                    leverage=webhook.open['leverage'],
                    status=OrderStatus.IN_PROGRESS,
                    binance_status=event.order_status,
                    binance_id=order_binance_id,
                    binance_position_id=binance_position_id

                )
                # session.add(binance_position)
                session.add(order)

            session.commit()
