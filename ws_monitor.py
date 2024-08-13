from typing import List, Dict

import sentry_sdk

from core.models.binance_position import PositionStatus
from core.models.monitor import  SymbolPosition
from core.models.orders import OrderType, OrderPositionSide, Order
from core.schemas.events.agg_trade import AggregatedTradeEvent
from core.schemas.events.order_trade_update import OrderTradeUpdate
from core.schemas.events.account_update import UpdateData
import json
from decimal import Decimal
from config import get_settings
from core.schemas.position import LongPosition, ShortPosition
from core.views.handle_orders import get_webhook_last, db_get_order_binance_position_id
from core.views.handle_positions import get_exist_position
from flows.order_new_flow import order_new_flow
from flows.tasks.binance_futures import client, check_position, get_order_id
from core.logger import logger
from binance.websocket.um_futures.websocket_client import UMFuturesWebsocketClient
from flows.agg_trade_flow import close_positions
from flows.order_filled_flow import order_filled_flow
from flows.order_cancel_flow import order_cancel_flow
from flows.tasks.orders_create import create_long_trailing_stop_order

settings = get_settings()


sentry_sdk.init(
    dsn="https://c167125710805940a14cc72b74bf2617@o103263.ingest.us.sentry.io/4507614078238720",
    traces_sample_rate=1.0,
    profiles_sample_rate=1.0,
)


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
            current_price = Decimal(event.price)

            if position.long_qty == 0:
                return None

            # ---- PNL CHECK --------
            pnl_diff = calculate_pnl(position, current_price)

            if pnl_diff > 0 and position.short_qty:
                logger.warning(f"={event.symbol} Profit: {pnl_diff} USDT")
                close_positions(position, event.symbol)
                position = SymbolPosition()
                return None

            # ---- TRAILING --------

            if not position.webhook:
                position.webhook = get_webhook_last(event.symbol)
                if not position.webhook:
                    return None

            if position.trailing_1 == 0 and position.trailing_2 == 0:
                position.trailing_1 = Decimal(position.webhook.settings.get('trail_1', 0))
                position.trailing_2 = Decimal(position.webhook.settings.get('trail_2', 0))

            activation_price = position.long_adjusted_break_even_price * (1 + position.trailing_1 / 100)
            logger.warning(f"{event.symbol} Trailing activation_price: {round(activation_price, 8)}")

            # Активация трейлинга происходит один раз
            if current_price >= activation_price and position.trailing_price is None:
                # Если трейлинг еще не активирован, активируем его
                new_trailing_price = activation_price * (1 - position.trailing_2 / 100)
                position.trailing_price = new_trailing_price
                logger.warning(f"{event.symbol} Trailing stop activated at: {round(position.trailing_price, 8)}")

            # Если цена trailing_price инициализирована
            elif current_price >= activation_price and position.trailing_price is not None:
                # Продолжаем обновлять trailing_price
                if current_price >= position.trailing_price + (
                        position.trailing_price * Decimal(position.webhook.settings.get('trail_step')) / 100):
                    new_trailing_price = current_price - (current_price * position.trailing_2 / 100)
                    if new_trailing_price > position.trailing_price:
                        position.trailing_price = new_trailing_price
                        logger.warning(f"{event.symbol} Current price: {round(current_price, 8)}")
                        logger.warning(
                        f"{event.symbol} Trailing stop updated to: {round(position.trailing_price, 8)}")

                # Проверка на достижение стоп-лосса
                if current_price <= position.trailing_price:
                    logger.warning(f"{event.symbol} Trailing stop triggered at: {round(current_price, 8)}")
                    close_positions(position, event.symbol)
                    position = SymbolPosition()

        elif event_type == 'ORDER_TRADE_UPDATE':
            event = OrderTradeUpdate.parse_obj(message_dict.get('o'))
            if event.symbol not in self.symbols:
                return None

            position: SymbolPosition = self.positions[event.symbol]

            our_order_type = None
            # todo: сделать сюда все типы наш-бинанс, и проверку вначале делать чтоб такого ордера в базе нет
            # choise from OrderType by event
            if event.position_side == 'SHORT' and event.side == 'SELL' and event.order_type == 'STOP':
                our_order_type = OrderType.SHORT_LIMIT
            elif event.order_type == 'STOP_MARKET' and event.side == 'SELL':
                our_order_type = OrderType.SHORT_MARKET_STOP_OPEN
            elif event.order_type == 'STOP_MARKET' and event.side == 'BUY':
                our_order_type = OrderType.SHORT_MARKET_STOP_LOSS
            elif event.order_type == 'MARKET' and event.position_side == 'SHORT':
                our_order_type = OrderType.SHORT_MARKET
            elif event.order_type == 'MARKET' and event.position_side == 'LONG':
                our_order_type = OrderType.LONG_MARKET
            elif event.order_type == 'LIMIT' and event.position_side == 'LONG' and event.side == 'SELL':
                our_order_type = OrderType.LONG_TAKE_PROFIT
            elif event.order_type == 'LIMIT' and event.position_side == 'LONG':
                our_order_type = OrderType.LONG_LIMIT
            elif event.order_type == 'LIMIT' and event.position_side == 'SHORT':
                our_order_type = OrderType.SHORT_LIMIT

            if event.order_status == 'FILLED':
                # if event.order_type == 'MARKET' and event.position_side == 'LONG':
                #     logger.warning(f"Order Market Filled: {event.order_status}, {event.order_type}")
                #     return None
                filled_order = order_filled_flow(event=event, position=position, order_type=our_order_type)
                if not filled_order:
                    order_new_flow(event, our_order_type)

            elif event.order_status == 'CANCELED':
                logger.warning(f"Order Canceled: {event.order_status}, {event.order_type}")
                order_cancel_flow(event)

            elif event.order_status == 'REJECTED':
                logger.warning(f"Order Rejected: {event.order_status}, {event.order_type}")
            elif event.order_status == 'EXPIRED':
                logger.warning(f"Order Expired: {event.order_status}, {event.order_type}")
            elif event.order_status == 'NEW':
                logger.warning(f"Order New: {event.order_status}, {event.order_type}")

                if our_order_type:
                    order_new_flow(event, our_order_type)

        elif event_type == 'ACCOUNT_UPDATE':
            event = UpdateData.parse_obj(message_dict['a'])
            self.handle_account_update(event)

    def handle_account_update(self, event: UpdateData):
        from core.schemas.events.base import Balance, Position
        from core.views.handle_positions import save_position

        webhook_id = get_webhook_last(event.positions[0].symbol).id

        for position in event.positions:
            symbol = position.symbol
            position: Position

            if symbol not in self.positions:
                continue

            if position.position_side == 'LONG':

                # если значения с 0 увеличилось, то это открытие позиции и отправляем в базу
                # если уменьшилось до 0 - закрытие позиции
                # или просто обновили если не 0
                status = PositionStatus.OPEN

                if position.position_amount != 0 and self.positions[symbol].long_qty == 0:
                    # open
                    logger.warning(f"Open position in {symbol} with {position.position_amount} amount")

                elif position.position_amount == 0:
                    # close
                    logger.warning(f"Close position in {symbol} with {position.position_amount} amount")
                    status = PositionStatus.CLOSED

                    position_binance = get_exist_position(
                        symbol=symbol,
                        webhook_id=webhook_id,
                        position_side=OrderPositionSide.LONG,
                        check_closed=False
                    )
                    if position_binance:
                        last_orders: Order = db_get_order_binance_position_id(position_binance.id)
                        # if last_orders:
                        #     self.positions[symbol].long_pnl = self.positions[symbol].calculate_pnl_long(last_orders[0].price)
                        # else:
                        order_binance = get_order_id(symbol, last_orders[0].binance_id)
                        if order_binance:
                            self.positions[symbol].long_pnl = self.positions[symbol].calculate_pnl_long(Decimal(order_binance.get('avgPrice')))

                else:
                    logger.warning(
                        f"Changed position in {symbol} from {self.positions[symbol].long_qty} to {position.position_amount}")

                    status = PositionStatus.UPDATED

                self.positions[symbol].long_qty = Decimal(abs(position.position_amount))
                self.positions[symbol].long_entry = Decimal(position.entry_price)
                self.positions[symbol].long_break_even_price = Decimal(position.breakeven_price)

                logger.info(f'UPDATE Long PNL: {self.positions[symbol].long_pnl}')
                logger.info(position)

                save_position(
                    position=self.positions[symbol],
                    position_side=OrderPositionSide.LONG,
                    symbol=symbol,
                    webhook_id=webhook_id,
                    status=status
                )

                if status == PositionStatus.CLOSED:
                    self.positions[symbol] = SymbolPosition(
                        long_qty=0,
                        long_entry=0,
                        long_break_even_price=0,
                        long_adjusted_break_even_price=0,
                    )

            elif position.position_side == 'SHORT':

                status = PositionStatus.OPEN

                if position.position_amount != 0 and self.positions[symbol].short_qty == 0:
                    # open
                    logger.warning(f"Open position in {symbol} with {position.position_amount} amount")

                elif position.position_amount == 0:
                    # close
                    logger.warning(f"Close position in {symbol} with {position.position_amount} amount")
                    status = PositionStatus.CLOSED

                    position_binance = get_exist_position(
                        symbol=symbol,
                        webhook_id=webhook_id,
                        position_side=OrderPositionSide.SHORT,
                        check_closed=False
                    )
                    if position_binance:
                        last_orders: Order = db_get_order_binance_position_id(position_binance.id)
                        order_binance = get_order_id(symbol, last_orders[0].binance_id)
                        if order_binance:
                            self.positions[symbol].short_pnl = self.positions[symbol].calculate_pnl_short(
                                Decimal(order_binance.get('avgPrice')))

                else:
                    logger.warning(
                        f"Changed position in {symbol} from {self.positions[symbol].short_qty} to {position.position_amount}")

                    status = PositionStatus.UPDATED

                self.positions[symbol].short_qty = Decimal(abs(position.position_amount))
                self.positions[symbol].short_entry = Decimal(position.entry_price)
                self.positions[symbol].short_break_even_price = Decimal(position.breakeven_price)
                logger.info(f'UPDATE Short PNL: {self.positions[symbol].short_pnl}')
                logger.info(position)

                save_position(
                    position=self.positions[symbol],
                    position_side=OrderPositionSide.SHORT,
                    symbol=symbol,
                    webhook_id=webhook_id,
                    status=status
                )

                if status == PositionStatus.CLOSED:
                    self.positions[symbol] = SymbolPosition(
                        short_qty=0,
                        short_entry=0,
                        short_break_even_price=0,
                        short_adjusted_break_even_price=0,
                    )


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
