from typing import List, Dict

from pydantic import BaseModel, Field

from core.models.monitor import TradeMonitorBase, SymbolPosition
from core.models.orders import OrderType
from core.schemas.events.agg_trade import AggregatedTradeEvent
from core.schemas.events.order_trade_update import OrderTradeUpdate
from core.schemas.events.account_update import UpdateData
import json
from decimal import Decimal
from config import get_settings
from core.schemas.position import LongPosition, ShortPosition
from flows.order_new_flow import order_new_flow
from flows.tasks.binance_futures import client, check_position
from core.logger import logger
from binance.websocket.um_futures.websocket_client import UMFuturesWebsocketClient
from flows.agg_trade_flow import close_positions
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
            position_long: LongPosition
            position_short: ShortPosition
            if position_long:
                self.positions[symbol].long_qty = position_long.positionAmt
                self.positions[symbol].long_entry = position_long.entryPrice
                self.positions[symbol].long_break_even_price = position_long.breakEvenPrice
                logger.warning(
                    f"{symbol} +LONG -> qty: {self.positions[symbol].long_qty}, Entry price: {self.positions[symbol].long_entry}")
            if position_short:
                self.positions[symbol].short_qty = position_short.positionAmt
                self.positions[symbol].short_entry = position_short.entryPrice
                self.positions[symbol].short_break_even_price = position_short.breakEvenPrice
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

            pnl_diff = calculate_pnl(position, Decimal(event.price))

            if pnl_diff > 0 and position.short_qty:
                logger.warning(f"=Profit: {pnl_diff} USDT")
                close_positions(position, event.symbol)
                self.positions[event.symbol] = SymbolPosition(
                    long_qty=0,
                    long_entry=0,
                    long_break_even_price=0,
                    long_adjusted_break_even_price=0,
                    short_qty=0,
                    short_entry=0,
                    short_break_even_price=0,
                    short_adjusted_break_even_price=0,
                )

        elif event_type == 'ORDER_TRADE_UPDATE':
            event = OrderTradeUpdate.parse_obj(message_dict.get('o'))
            if event.symbol not in self.symbols:
                return None

            position: SymbolPosition = self.positions[event.symbol]

            if event.order_status == 'FILLED':
                if event.order_type == 'MARKET' and event.position_side == 'LONG':
                    logger.warning(f"Order Market Filled: {event.order_status}, {event.order_type}")
                    return None
                order_filled_flow(event=event, position=position)

            elif event.order_status == 'CANCELED':
                logger.warning(f"Order Canceled: {event.order_status}, {event.order_type}")
                order_cancel_flow(event)

            elif event.order_status == 'REJECTED':
                logger.warning(f"Order Rejected: {event.order_status}, {event.order_type}")
            elif event.order_status == 'EXPIRED':
                logger.warning(f"Order Expired: {event.order_status}, {event.order_type}")
            elif event.order_status == 'NEW':
                logger.warning(f"Order New: {event.order_status}, {event.order_type}")

                our_order_type = None
                # todo: сделать сюда все типы наш-бинанс, и проверку вначале делать чтоб такого ордера в базе нет
                # choise from OrderType by event
                if event.position_side == 'SHORT' and event.side == 'SELL' and event.order_type == 'STOP':
                    our_order_type = OrderType.SHORT_LIMIT
                elif event.order_type == 'STOP_MARKET' and event.side == 'SELL':
                    our_order_type = OrderType.SHORT_MARKET_STOP_OPEN
                elif event.order_type == 'STOP_MARKET' and event.side == 'BUY':
                    our_order_type = OrderType.SHORT_MARKET_STOP_LOSS

                if our_order_type:
                    order_new_flow(event, our_order_type)

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
                self.positions[symbol].long_entry = Decimal(position.entry_price)
                self.positions[symbol].long_break_even_price = Decimal(position.breakeven_price)
                logger.info(f'UPDATE Long PNL: {position.unrealized_pnl}')
                logger.info(position)

            elif position.position_side == 'SHORT':
                if position.position_amount != self.positions[symbol].short_qty:
                    logger.warning(
                        f"Changed position in {symbol} from {self.positions[symbol].short_qty} to {position.position_amount}")
                self.positions[symbol].short_qty = Decimal(position.position_amount)
                self.positions[symbol].short_entry = Decimal(position.entry_price)
                self.positions[symbol].short_break_even_price = Decimal(position.breakeven_price)
                logger.info(f'UPDATE Short PNL: {position.unrealized_pnl}')
                logger.info(position)


def calculate_pnl(position: SymbolPosition, current_price: Decimal):
    long_pnl = 0
    short_pnl = 0

    if position.long_qty != 0:
        long_pnl = position.calculate_pnl_long(current_price)

    if position.short_qty != 0:
        short_pnl = position.calculate_pnl_short(current_price)

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

    # symbols = ['UNFIUSDT', '1000FLOKIUSDT', '1000LUNCUSDT', '1000SHIBUSDT', '1000XECUSDT', '1INCHUSDT']
    check_orders([symbol])
    trade_monitor = TradeMonitor([symbol])
    trade_monitor.start_monitor_events()


if __name__ == '__main__':
    main()
