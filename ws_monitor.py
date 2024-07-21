from prefect.deployments import run_deployment

from core.models.monitor import TradeMonitorBase
from core.models.orders import OrderStatus
from core.schemas.events.agg_trade import AggregatedTradeEvent
from core.schemas.events.order_trade_update import OrderTradeUpdate
from core.schemas.events.account_update import UpdateData
import json
from decimal import Decimal
from config import get_settings
from core.views.handle_orders import db_set_order_status
from flows.agg_trade_flow import calculate_pnl, close_position_by_pnl_flow
from flows.order_cancel_flow import order_cancel_flow
from flows.tasks.binance_futures import client, check_position
from core.logger import logger
from flows.order_filled_flow import order_filled_flow

settings = get_settings()

# # Sentry Initialization
# sentry_sdk.init(
#     dsn="https://c167125710805940a14cc72b74bf2617@o103263.ingest.us.sentry.io/4507614078238720",
#     traces_sample_rate=1.0,
#     profiles_sample_rate=1.0,
# )

settings = get_settings()


class TradeMonitor(TradeMonitorBase):

    def start_monitor_events(self):
        listen_key = client.new_listen_key().get('listenKey')
        for symbol in self.symbols:
            position_long, position_short = check_position(symbol)
            if position_long:
                self.long_position_qty = position_long.positionAmt
                self.long_entry_price = position_long.breakEvenPrice
                logger.warning(f"{symbol} +LONG -> qty: {self.long_position_qty}, Entry price: {self.long_entry_price}")
            if position_short:
                self.short_position_qty = position_short.positionAmt
                self.short_entry_price = position_short.breakEvenPrice
                logger.warning(
                    f"{symbol} -SHORT -> qty: {self.short_position_qty}, Entry price: {self.short_entry_price}")
            self.client.agg_trade(symbol)

        self.client.user_data(listen_key=listen_key)

    def on_message(self, ws, msg):
        message_dict = json.loads(msg)
        event_type = message_dict.get('e')

        if event_type == 'aggTrade':
            event = AggregatedTradeEvent.parse_obj(message_dict)
            pnl_diff = calculate_pnl(self, event)

            if pnl_diff > 0:
                logger.warning(f"=Profit: {pnl_diff} USDT")
                close_position_by_pnl_flow(self, event)

        if event_type == 'ORDER_TRADE_UPDATE':
            event = OrderTradeUpdate.parse_obj(message_dict.get('o'))
            if event.symbol not in self.symbols:
                return None

            if event.order_status == 'FILLED':
                if event.order_type == 'MARKET':
                    logger.warning(f"Order Market Filled: {event.order_status}, {event.order_type}")
                    return None
                order_filled_flow(event)

            elif event.order_status == 'CANCELED':
                logger.warning(f"Order Canceled: {event.order_status}, {event.order_type}")
                order_cancel_flow(event)

        elif event_type == 'ACCOUNT_UPDATE':
            event = UpdateData.parse_obj(message_dict['a'])
            # account_update_flow(event)
            self.handle_account_update(event)

    def handle_account_update(self, event: UpdateData):
        for position in event.positions:
            if position.position_side == 'LONG':

                if position.position_amount != self.long_position_qty:
                    logger.warning(f"Changed position in {position.symbol} from {self.long_position_qty} to {position.position_amount}")
                    # todo: cancel tp order and set new

                self.long_position_qty = Decimal(position.position_amount)
                self.long_entry_price = Decimal(position.breakeven_price)
                logger.info(f'UPDATE Long PNL: {position.unrealized_pnl}')
                logger.info(position)
            elif position.position_side == 'SHORT':
                self.short_position_qty = Decimal(position.position_amount)
                self.short_entry_price = Decimal(position.breakeven_price)
                logger.info(f'UPDATE Short PNL: {position.unrealized_pnl}')
                logger.info(position)


def check_orders(symbols):
    for symbol in symbols:
        position_long, position_short = check_position(symbol)
        if not position_long.positionAmt:
            logger.warning(f"no position in {symbol}")
            # orders = session.exec(select(Order).where(Order.status == OrderStatus.IN_PROGRESS)).all()
            # for order in orders:
            #     def cancel_order(session):
            #         order.status = OrderStatus.CANCELED
            #         session.add(order)
            #         session.commit()
            #     execute_sqlmodel_query(cancel_order)


import click


@click.command()
@click.option("--symbol", prompt="Symbol", default="1000FLOKIUSDT", show_default=True,
              help="Enter the trading symbol (default: 1000FLOKIUSDT)")
def main(symbol):
    check_orders([symbol])
    trade_monitor = TradeMonitor([symbol])
    trade_monitor.start_monitor_events()


if __name__ == '__main__':
    main()
