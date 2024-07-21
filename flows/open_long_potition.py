from prefect import task, flow, tags, get_run_logger
from prefect.task_runners import ConcurrentTaskRunner

from core.schemas.webhook import WebhookPayload

from flows.tasks.orders_create import create_long_market_order, create_long_tp_order
from flows.tasks.orders_processing import grid_make_long_limit_order


@flow(task_runner=ConcurrentTaskRunner(), log_prints=True)
async def open_long_position(payload: WebhookPayload, webhook_id):
    with tags(payload.symbol, webhook_id):

        first_order = create_long_market_order(
            symbol=payload.symbol,
            quantity=payload.open.amount,
            leverage=payload.open.leverage,
            webhook_id=webhook_id,
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
