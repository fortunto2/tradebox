from prefect import flow, tags, get_run_logger, task
from prefect.task_runners import ConcurrentTaskRunner

from core.schemas.position import LongPosition, ShortPosition
from core.schemas.webhook import WebhookPayload
from flows.tasks.binance_futures import cancel_open_orders, check_position
from core.models.orders import OrderSide
from flows.tasks.orders_create import create_short_market_order, create_long_market_order


@flow(task_runner=ConcurrentTaskRunner())
async def close_positions(symbol: str, close_short=True, close_long=True):

    with tags(symbol):
        logger = get_run_logger()

        status_cancel = cancel_open_orders(symbol=symbol)

        logger.info(f">>> Cancel all open orders: {status_cancel}")

        position_long, position_short = check_position(symbol=symbol)
        position_long: LongPosition
        position_short: ShortPosition

        # -- LONG ----------
        if abs(position_long.positionAmt) > 0 and close_long:
            create_long_market_order(
                symbol=symbol,
                quantity=abs(position_long.positionAmt),
                side=OrderSide.SELL
            )

        # -- Short----------
        if abs(position_short.positionAmt) > 0 and close_short:

            create_short_market_order(
                symbol=symbol,
                quantity=abs(position_short.positionAmt),
                side=OrderSide.BUY
            )

        return True


@flow(task_runner=ConcurrentTaskRunner())
async def open_long_position(payload: WebhookPayload, webhook_id):
    with tags(payload.symbol, webhook_id):

        market_order = create_long_market_order(
            symbol=payload.symbol,
            quantity=payload.open.amount,
            payload=payload
        )

