from decimal import Decimal
from prefect import flow, tags, get_run_logger
from prefect.task_runners import ConcurrentTaskRunner

from core.models.binance_position import PositionStatus
from core.schemas.position import LongPosition, ShortPosition
from core.views.handle_positions import save_position
from flows.tasks.binance_futures import cancel_open_orders, check_position
from core.models.monitor import TradeMonitorBase, SymbolPosition
from core.models.orders import OrderSide, OrderPositionSide
from core.views.handle_orders import get_webhook_last
from flows.tasks.orders_create import create_short_market_order, create_long_market_order


@flow(task_runner=ConcurrentTaskRunner())
async def close_positions(position: SymbolPosition, symbol: str, close_short=True, close_long=True):

    with tags(symbol):
        logger = get_run_logger()

        status_cancel = cancel_open_orders(symbol=symbol)

        if not position.webhook.id:
            position.webhook = get_webhook_last(symbol)

        leverage = position.webhook.open.get('leverage', position.webhook.open['leverage'])

        logger.info(f">>> Cancel all open orders: {status_cancel}")

        position_long, position_short = check_position(symbol=symbol)
        position_long: LongPosition
        position_short: ShortPosition

        # -- LONG ----------
        if abs(position_long.positionAmt) > 0:
            create_long_market_order(
                symbol=symbol,
                quantity=abs(position_long.positionAmt),
                leverage=leverage,
                webhook_id=position.webhook.id,
                side=OrderSide.SELL
            )
            save_position(
                position=position,
                position_side=OrderPositionSide.SHORT,
                symbol=symbol,
                webhook_id=position.webhook.id,
                status=PositionStatus.CLOSED
            )

        # -- Short----------
        if position_short.positionAmt > 0:
            create_short_market_order(
                symbol=symbol,
                quantity=abs(position_short.positionAmt),
                leverage=leverage,
                webhook_id=position.webhook.id,
                side=OrderSide.BUY
            )
            save_position(
                position=position,
                position_side=OrderPositionSide.SHORT,
                symbol=symbol,
                webhook_id=position.webhook.id,
                status=PositionStatus.CLOSED
            )

        return True

        # save_position(event.symbol, "LONG", long_position_qty, long_entry_price, long_pnl)
        # save_position(event.symbol, "SHORT", short_position_qty, short_entry_price, short_pnl)
