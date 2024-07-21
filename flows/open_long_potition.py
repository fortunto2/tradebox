from prefect import task, flow, tags, get_run_logger
from prefect.task_runners import ConcurrentTaskRunner

from core.grid import calculate_grid_orders
from core.logger import logger
from core.models.monitor import SymbolPosition
from core.schemas.position import LongPosition
from core.schemas.webhook import WebhookPayload
from flows.tasks.binance_futures import check_position

from flows.tasks.orders_create import create_long_market_order, create_long_tp_order
from flows.tasks.orders_processing import grid_make_long_limit_order


@flow(task_runner=ConcurrentTaskRunner())
async def open_long_position(payload: WebhookPayload, webhook_id, position_long: LongPosition):
    with tags(payload.symbol, webhook_id):

        grid_orders = calculate_grid_orders(payload, position_long.markPrice)

        if grid_orders["sufficient_funds"] is False:
            logger.error("Недостаточно средств для открытия позиции.")
            return False

        first_order = create_long_market_order(
            symbol=payload.symbol,
            quantity=payload.open.amount,
            leverage=payload.open.leverage,
            webhook_id=webhook_id
        )

        tp_order = create_long_tp_order.submit(
            symbol=payload.symbol,
            tp=payload.settings.tp,
            leverage=payload.open.leverage,
            webhook_id=webhook_id,
        )

        # первый запуск создание пары ордеров лимитных по сетке
        grid_make_long_limit_order(
            webhook_id=webhook_id,
            payload=payload,
        )
