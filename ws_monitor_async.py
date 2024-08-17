import asyncio
from typing import List, Dict
from decimal import Decimal
import json

import sentry_sdk
from binance import AsyncClient, BinanceSocketManager
from binance.exceptions import BinanceAPIException

from core.models.binance_position import PositionStatus, BinancePosition
from core.models.monitor import SymbolPosition
from core.models.orders import OrderType, OrderPositionSide, Order
from core.schemas.events.agg_trade import AggregatedTradeEvent
from core.schemas.events.order_trade_update import OrderTradeUpdate
from core.schemas.events.account_update import UpdateData
from config import get_settings
from core.schemas.position import LongPosition, ShortPosition
from core.views.handle_orders import get_webhook_last, db_get_order_binance_position_id
from core.views.handle_positions import get_exist_position, save_position
from flows.order_new_flow import order_new_flow
from flows.tasks.binance_futures import check_position, get_order_id
from core.logger import logger
from flows.agg_trade_flow import close_positions
from flows.order_filled_flow import order_filled_flow
from flows.order_cancel_flow import order_cancel_flow

settings = get_settings()

sentry_sdk.init(
    dsn="https://c167125710805940a14cc72b74bf2617@o103263.ingest.us.sentry.io/4507614078238720",
    traces_sample_rate=1.0,
    profiles_sample_rate=1.0,
)


class TradeMonitor:
    def __init__(self, client: AsyncClient, symbols: List[str]):
        self.client = client
        self.bsm = BinanceSocketManager(client)

        self.symbols = symbols
        self.positions: Dict[str, SymbolPosition] = {symbol: SymbolPosition() for symbol in symbols}

    async def start_monitor_events(self):
        tasks = [self.monitor_symbol(symbol) for symbol in self.symbols]
        tasks.append(self.monitor_user_data())  # Добавляем задачу для мониторинга пользовательских данных
        await asyncio.gather(*tasks)

    async def monitor_symbol(self, symbol: str):
        """
        https://developers.binance.com/docs/binance-spot-api-docs/web-socket-streams
        :param symbol:
        :return:
        """
        await self.initialize_positions(symbol)

        streams = [
            f'{symbol.lower()}@aggTrade',  # Stream для агрегированных торгов
        ]
        try:

            async with self.bsm.futures_multiplex_socket(streams) as stream:
                while True:
                    msg = await stream.recv()
                    if msg:
                        await self.on_message(msg.get('data'))

        except BinanceAPIException as e:
            logger.error(f"Binance API error for symbol {symbol}: {e}")
        except asyncio.CancelledError:
            logger.warning("Symbol data stream monitoring was cancelled.")
        except Exception as e:
            logger.error(f"Error in monitor_symbol for {symbol}: {e}")
        finally:
            await self.client.close_connection()

    async def monitor_user_data(self):

        try:
            async with self.bsm.futures_user_socket() as user_stream:
                while True:
                    user_msg = await user_stream.recv()
                    if user_msg:
                        await self.on_message(user_msg)

        except BinanceAPIException as e:
            logger.error(f"Binance API error in user data stream: {e}")
        except asyncio.CancelledError:
            logger.warning("User data stream monitoring was cancelled.")

        except Exception as e:
            logger.error(f"Error in user data stream: {e}")
        finally:
            await self.client.close_connection()

    async def initialize_positions(self, symbol: str):
        self.positions[symbol].webhook = get_webhook_last(symbol)

        position_long, position_short = check_position(symbol)
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

        await self.check_closed_positions_status(symbol)

    async def on_message(self, msg):
        event_type = msg.get('e')

        if event_type == 'aggTrade':
            await self.handle_agg_trade(AggregatedTradeEvent.parse_obj(msg))
        elif event_type == 'ORDER_TRADE_UPDATE':
            await self.handle_order_update(OrderTradeUpdate.parse_obj(msg.get('o')))
        elif event_type == 'ACCOUNT_UPDATE':
            await self.handle_account_update(UpdateData.parse_obj(msg['a']))
        else:
            logger.info(f"Unhandled event type: {event_type}")

    async def handle_agg_trade(self, event: AggregatedTradeEvent):
        position: SymbolPosition = self.positions.get(event.symbol)
        # if not position or position.long_qty == 0:
        #     return None

        current_price = Decimal(event.price)
        pnl_diff = self.calculate_pnl(position, current_price)
        logger.warning(f"={event.symbol} PnL: {pnl_diff} USDT")

        if pnl_diff > 0 and position.short_qty:
            logger.warning(f"={event.symbol} Profit: {pnl_diff} USDT")
            await self.close_positions(event.symbol)
            return None

        # Trailing logic (asynchronous)
        await self.handle_trailing(position, event.symbol, current_price)

    async def handle_trailing(self, position, symbol, current_price):
        if not position.webhook:
            position.webhook = get_webhook_last(symbol)
            if not position.webhook:
                return None

        if position.trailing_1 == 0 and position.trailing_2 == 0:
            position.trailing_1 = Decimal(position.webhook.settings.get('trail_1', 0)) - Decimal(0.025)
            position.trailing_2 = Decimal(position.webhook.settings.get('trail_2', 0))

        if position.long_qty > 0:
            activation_price = position.long_adjusted_break_even_price * (1 + position.trailing_1 / 100)
            if activation_price != position.activation_price:
                logger.warning(f"{symbol} Trailing activation_price: {round(activation_price, 8)}")
                position.activation_price = activation_price
                save_position(
                    position=position,
                    position_side=OrderPositionSide.LONG,
                    symbol=symbol,
                    webhook_id=position.webhook.id,
                    status=PositionStatus.UPDATED
                )
        else:
            logger.warning(f"{symbol} No open position found, skipping trailing calculation")
            position.activation_price = None
            position.trailing_price = None
            return

        if current_price >= activation_price:
            if position.trailing_price is None:
                position.trailing_price = activation_price * (1 - position.trailing_2 / 100)
                logger.warning(f"{symbol} Trailing stop activated at: {round(position.trailing_price, 8)}")

            else:
                if current_price >= position.trailing_price + (
                        position.trailing_price * Decimal(position.webhook.settings.get('trail_step')) / 100):
                    new_trailing_price = current_price - (current_price * position.trailing_2 / 100)
                    if new_trailing_price > position.trailing_price:
                        position.trailing_price = new_trailing_price
                        logger.warning(f"{symbol} Current price: {round(current_price, 8)}")
                        logger.warning(f"{symbol} Trailing stop updated to: {round(position.trailing_price, 8)}")

        if position.trailing_price is not None and current_price <= position.trailing_price:
            logger.warning(f"{symbol} Trailing stop triggered at: {round(current_price, 8)}")
            await self.close_positions(symbol)

    async def handle_order_update(self, event: OrderTradeUpdate):
        if event.symbol not in self.symbols:
            return None

        position: SymbolPosition = self.positions[event.symbol]
        our_order_type = None

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
            filled_order = await order_filled_flow(event=event, position=position, order_type=our_order_type)
            if not filled_order:
                await order_new_flow(event, our_order_type)
        elif event.order_status == 'CANCELED':
            logger.warning(f"Order Canceled: {event.order_status}, {event.order_type}")
            await order_cancel_flow(event)
        elif event.order_status == 'REJECTED':
            logger.warning(f"Order Rejected: {event.order_status}, {event.order_type}")
        elif event.order_status == 'EXPIRED':
            logger.warning(f"Order Expired: {event.order_status}, {event.order_type}")
        elif event.order_status == 'NEW':
            logger.warning(f"Order New: {event.order_status}, {event.order_type}")
            if our_order_type:
                await order_new_flow(event, our_order_type)

    async def handle_account_update(self, event: UpdateData):

        if not event.positions:
            logger.warning("No positions found in account update")
            return None
        symbol = event.positions[0].symbol
        # if not self.positions[symbol].webhook:
        self.positions[symbol].webhook = get_webhook_last(symbol)

        for position in event.positions:
            symbol = position.symbol
            if symbol not in self.positions:
                continue

            if position.position_side == 'LONG':
                await self.update_long_position(position, symbol)
            elif position.position_side == 'SHORT':
                await self.update_short_position(position, symbol)

    async def update_long_position(self, position, symbol):
        status = PositionStatus.OPEN

        webhook_id = self.positions[symbol].webhook.id

        if position.position_amount != 0 and self.positions[symbol].long_qty == 0:
            logger.warning(f"Open position in {symbol} with {position.position_amount} amount")
        elif position.position_amount == 0:
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
                order_binance = get_order_id(symbol, last_orders[0].binance_id)
                if order_binance:
                    self.positions[symbol].long_pnl = self.positions[symbol].calculate_pnl_long(
                        Decimal(order_binance.get('avgPrice')))
        else:
            logger.warning(
                f"Changed position in {symbol} from {self.positions[symbol].long_qty} to {position.position_amount}")
            status = PositionStatus.UPDATED

        self.positions[symbol].long_qty = Decimal(abs(position.position_amount))
        self.positions[symbol].long_entry = Decimal(position.entry_price)
        self.positions[symbol].long_break_even_price = Decimal(position.breakeven_price)

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
                webhook={}
            )

    async def update_short_position(self, position, symbol):
        status = PositionStatus.OPEN

        webhook_id = self.positions[symbol].webhook.id

        if position.position_amount != 0 and self.positions[symbol].short_qty == 0:
            logger.warning(f"Open position in {symbol} with {position.position_amount} amount")
        elif position.position_amount == 0:
            logger.warning(f"Close position in {symbol} with {position.position_amount} amount")
            status = PositionStatus.CLOSED
            position_binance = get_exist_position(symbol=symbol, webhook_id=webhook_id,
                                                  position_side=OrderPositionSide.SHORT, check_closed=False)
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

        save_position(position=self.positions[symbol], position_side=OrderPositionSide.SHORT, symbol=symbol,
                      webhook_id=webhook_id, status=status)
        if status == PositionStatus.CLOSED:
            self.positions[symbol] = SymbolPosition(
                short_qty=0,
                short_entry=0,
                short_break_even_price=0,
                short_adjusted_break_even_price=0,
                webhook={}
            )

    async def close_positions(self, symbol: str):
        position = self.positions[symbol]
        await close_positions(position, symbol)
        self.positions[symbol] = SymbolPosition(
            long_qty=0,
            long_entry=0,
            long_break_even_price=0,
            long_adjusted_break_even_price=0,
            short_qty=0,
            short_entry=0,
            short_break_even_price=0,
            short_adjusted_break_even_price=0,
            webhook={}
        )

    async def check_closed_positions_status(self, symbol):
        position = self.positions.get(symbol)

        position_long, position_short = check_position(symbol)

        position_long_open_in_db: BinancePosition = get_exist_position(
            symbol=symbol,
            position_side=OrderPositionSide.LONG,
        )

        if position_long_open_in_db:
            if not position_long.positionAmt:
                logger.warning(f"no position in {symbol}")
                save_position(
                    position=position,
                    position_side=OrderPositionSide.LONG,
                    symbol=symbol,
                    webhook_id=position_long_open_in_db.webhook_id,
                    status=PositionStatus.CLOSED
                )

        position_short_open_in_db: BinancePosition = get_exist_position(
            symbol=symbol,
            position_side=OrderPositionSide.SHORT,
        )

        if position_short_open_in_db:
            if not position_short.positionAmt:
                logger.warning(f"no position in {symbol}")
                save_position(
                    position=position,
                    position_side=OrderPositionSide.SHORT,
                    symbol=symbol,
                    webhook_id=position_short_open_in_db.webhook_id,
                    status=PositionStatus.CLOSED
                )

    def calculate_pnl(self, position: SymbolPosition, current_price: Decimal):
        long_pnl = 0
        short_pnl = 0

        if position.long_qty != 0:
            long_pnl = position.calculate_pnl_long(current_price)

        if position.short_qty != 0:
            short_pnl = position.calculate_pnl_short(current_price)

        return round(long_pnl + short_pnl, 2)


async def start(symbols):
    client = await AsyncClient.create(
        api_key=settings.BINANCE_API_KEY,
        api_secret=settings.BINANCE_API_SECRET
    )
    trade_monitor = TradeMonitor(client, symbols)
    await trade_monitor.start_monitor_events()


import click


@click.command()
@click.option("--symbol", prompt="Symbol", default="1000FLOKIUSDT", show_default=True,
              help="Enter the trading symbol (default: 1000FLOKIUSDT)")
def main(symbol):
    asyncio.run(start([symbol]))


if __name__ == '__main__':
    main()
