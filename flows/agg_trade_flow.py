from decimal import Decimal
from prefect import flow, tags
from prefect.task_runners import ConcurrentTaskRunner

from core.logger import logger
from flows.tasks.binance_futures import cancel_open_orders
from core.models.monitor import TradeMonitorBase
from core.models.orders import OrderSide
from core.schemas.events.agg_trade import AggregatedTradeEvent
from core.views.handle_orders import get_webhook_last
from flows.tasks.orders_create import create_short_market_order, create_long_market_order


def calculate_pnl(self: TradeMonitorBase, event: AggregatedTradeEvent):
    trade_price = Decimal(event.price)
    long_pnl = 0

    if self.long_position_qty != 0:
        long_pnl = round((trade_price - self.long_entry_price) * self.long_position_qty, 2)

    if self.short_position_qty != 0:
        short_pnl = round((trade_price - self.short_entry_price) * self.short_position_qty, 2)
        _diff = round(long_pnl + short_pnl - Decimal(0.01), 2)

        return _diff

    return False


@flow(task_runner=ConcurrentTaskRunner())
def close_position_by_pnl_flow(self: TradeMonitorBase, event: AggregatedTradeEvent):
    with tags(event.symbol):
        status_cancel = cancel_open_orders(symbol=event.symbol)
        webhook = get_webhook_last(event.symbol)
        leverage = webhook.open.get('leverage', webhook.open['leverage'])

        logger.info(f">>> Cancel all open orders: {status_cancel}")

        create_short_market_order(
            symbol=event.symbol,
            quantity=abs(self.short_position_qty),
            leverage=leverage,
            webhook_id=webhook.id,
            side=OrderSide.BUY,
        )
        create_long_market_order(
            symbol=event.symbol,
            quantity=self.long_position_qty,
            leverage=leverage,
            webhook_id=webhook.id,
            side=OrderSide.SELL,
        )

        # save_position(event.symbol, "LONG", long_position_qty, long_entry_price, long_pnl)
        # save_position(event.symbol, "SHORT", short_position_qty, short_entry_price, short_pnl)
