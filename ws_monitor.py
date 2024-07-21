from typing import List, Dict

from pydantic import BaseModel, Field

from core.models.monitor import TradeMonitorBase, SymbolPosition
from core.schemas.events.agg_trade import AggregatedTradeEvent
from core.schemas.events.order_trade_update import OrderTradeUpdate
from core.schemas.events.account_update import UpdateData
import json
from decimal import Decimal
from config import get_settings
from flows.tasks.binance_futures import client, check_position
from core.logger import logger
from binance.websocket.um_futures.websocket_client import UMFuturesWebsocketClient
from flows.agg_trade_flow import close_position_by_pnl_flow
from flows.order_filled_flow import order_filled_flow
from flows.order_cancel_flow import order_cancel_flow

settings = get_settings()

# # Sentry Initialization
# sentry_sdk.init(
#     dsn="https://c167125710805940a14cc72b74bf2617@o103263.ingest.us.sentry.io/4507614078238720",
#     traces_sample_rate=1.0,
#     profiles_sample_rate=1.0,
# )

settings = get_settings()


class TradeMonitor:

    def __init__(self, symbols: List[str]):
        self.symbols = symbols
        self.positions: Dict[str, SymbolPosition] = {symbol: SymbolPosition() for symbol in symbols}
        self.client = UMFuturesWebsocketClient(on_message=self.on_message)
        # super().__init__(symbols)

    def start_monitor_events(self):
        listen_key = client.new_listen_key().get('listenKey')
        for symbol in self.symbols:
            position_long, position_short = check_position(symbol)
            if position_long:
                self.positions[symbol].long_qty = position_long.positionAmt
                self.positions[symbol].long_entry = position_long.breakEvenPrice
                logger.warning(
                    f"{symbol} +LONG -> qty: {self.positions[symbol].long_qty}, Entry price: {self.positions[symbol].long_entry}")
            if position_short:
                self.positions[symbol].short_qty = position_short.positionAmt
                self.positions[symbol].short_entry = position_short.breakEvenPrice
                logger.warning(
                    f"{symbol} -SHORT -> qty: {self.positions[symbol].short_qty}, Entry price: {self.positions[symbol].short_entry}")
            self.client.agg_trade(symbol)
        self.client.user_data(listen_key=listen_key)

    def on_message(self, ws, msg):

        message_dict = json.loads(msg)
        event_type = message_dict.get('e')

        if event_type == 'aggTrade':
            event = AggregatedTradeEvent.parse_obj(message_dict)
            position: SymbolPosition = self.positions[event.symbol]

            pnl_diff = calculate_pnl(position, event)

            if pnl_diff > 0:
                logger.warning(f"=Profit: {pnl_diff} USDT")
                close_position_by_pnl_flow(position, event)

        elif event_type == 'ORDER_TRADE_UPDATE':
            event = OrderTradeUpdate.parse_obj(message_dict.get('o'))
            if event.symbol not in self.symbols:
                return None
            # position: SymbolPosition = self.positions[event.symbol]

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
            self.handle_account_update(event)

    def handle_account_update(self, event: UpdateData):
        for position in event.positions:
            symbol = position.symbol

            if symbol not in self.positions:
                continue

            if position.position_side == 'LONG':
                if position.position_amount != self.positions[symbol].long_qty:
                    logger.warning(
                        f"Changed position in {symbol} from {self.positions[symbol].long_qty} to {position.position_amount}")
                self.positions[symbol].long_qty = Decimal(position.position_amount)
                self.positions[symbol].long_entry = Decimal(position.breakeven_price)
                logger.info(f'UPDATE Long PNL: {position.unrealized_pnl}')
                logger.info(position)

            elif position.position_side == 'SHORT':
                if position.position_amount != self.positions[symbol].short_qty:
                    logger.warning(
                        f"Changed position in {symbol} from {self.positions[symbol].short_qty} to {position.position_amount}")
                self.positions[symbol].short_qty = Decimal(position.position_amount)
                self.positions[symbol].short_entry = Decimal(position.breakeven_price)
                logger.info(f'UPDATE Short PNL: {position.unrealized_pnl}')
                logger.info(position)


def calculate_pnl(position: SymbolPosition, event: AggregatedTradeEvent):
    trade_price = Decimal(event.price)
    long_pnl = 0
    short_pnl = 0

    if position.long_qty != 0:
        long_pnl = round((trade_price - position.long_entry) * position.long_qty, 2)

    if position.short_qty != 0:
        short_pnl = round((trade_price - position.short_entry) * position.short_qty, 2)

    return round(long_pnl + short_pnl, 2)


def check_orders(symbols: List[str]):
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
