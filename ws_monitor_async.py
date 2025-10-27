import asyncio
import traceback
from asyncio import Queue
from typing import List, Dict
from decimal import Decimal

import sentry_sdk
from pydantic import BaseModel, Field
from unicorn_binance_websocket_api import BinanceWebSocketApiManager

from core.models.binance_position import PositionStatus, BinancePosition
from core.models.orders import OrderType, OrderPositionSide, Order, OrderStatus, OrderSide
from core.schemas.events.agg_trade import AggregatedTradeEvent
from core.schemas.events.base import Position
from core.schemas.events.order_trade_update import OrderTradeUpdate
from core.schemas.events.account_update import UpdateData
from config import get_settings
from core.views.handle_positions import get_exist_position, close_position_task, update_position_task, \
    open_position_task
from core.logger import logger
# Lazy imports to avoid Prefect/Pydantic compatibility issues at module level
# from flows.order_cancel_flow import order_cancel_flow
# from flows.order_new_flow import order_new_flow
# from flows.positions_flow import close_positions
# from flows.order_filled_flow import order_filled_flow
from flows.tasks.binance_futures import get_position_closed_pnl
from flows.tasks.orders_create import cancel_tp_order
from flows.tasks.positions_processing import check_closed_positions_status

settings = get_settings()

if settings.SENTRY_DSN:
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        traces_sample_rate=settings.SENTRY_TRACES_SAMPLE_RATE,
        profiles_sample_rate=settings.SENTRY_PROFILES_SAMPLE_RATE,
    )


class SymbolPositionState(BaseModel):
    """
    Состояние различных переменных кешируем по символу для работы в вебсокетах без базы
    """
    long_trailing_price: Decimal = Field(default_factory=lambda: Decimal(0))
    short_trailing_price: Decimal = Field(default_factory=lambda: Decimal(0))
    pnl_diff: Decimal = Field(default_factory=lambda: Decimal(0))
    old_activation_price: Decimal = Field(default_factory=lambda: Decimal(0))


class TradeMonitor:
    def __init__(self, symbols: List[str]):
        # UNICORN WebSocket manager - handles reconnect and keepalive automatically
        self.ubwa = BinanceWebSocketApiManager(
            exchange="binance.com-futures",
            output_default="UnicornFy"  # Automatically normalizes messages
        )

        self.symbols = symbols
        print(f"Monitoring symbols: {symbols}")
        self.state: Dict[str, SymbolPositionState] = {symbol: SymbolPositionState() for symbol in symbols}
        self.message_queue = Queue(maxsize=10000)

    async def start_monitor(self):
        """Start monitoring all streams"""
        # Check closed positions for all symbols
        for symbol in self.symbols:
            await check_closed_positions_status(symbol)

        # Create aggTrade streams for each symbol
        for symbol in self.symbols:
            self.ubwa.create_stream(
                ['aggTrade'],
                [symbol.lower()],
                stream_label=f"{symbol}_aggTrade"
            )
            logger.info(f"Created aggTrade stream for {symbol}")

        # Create user data stream with automatic keepalive
        self.ubwa.create_stream(
            ['arr'],  # Account, orders, and positions updates
            ['!userData'],
            api_key=settings.BINANCE_API_KEY,
            api_secret=settings.BINANCE_API_SECRET,
            stream_label="user_data"
        )
        logger.info("Created user data stream")

        # Start processing messages
        await self.process_streams()

    async def process_streams(self):
        """Process messages from all streams"""
        while True:
            try:
                # Get oldest message from stream buffer (FIFO)
                msg = self.ubwa.pop_stream_data_from_stream_buffer()

                if msg:
                    # UnicornFy normalizes the message format
                    await self.on_message(msg)
                else:
                    # Small sleep to avoid busy loop when no messages
                    await asyncio.sleep(0.01)

            except Exception as e:
                logger.error(f"Error processing stream: {e}")
                logger.error(traceback.format_exc())
                await asyncio.sleep(1)

    async def on_message(self, msg):
        """Route messages to appropriate handlers"""
        event_type = msg.get('event_type')

        if event_type == 'aggTrade':
            await self.handle_agg_trade(AggregatedTradeEvent.parse_obj(msg))
        elif event_type == 'ORDER_TRADE_UPDATE':
            await self.handle_order_update(OrderTradeUpdate.parse_obj(msg.get('order')))
        elif event_type == 'ACCOUNT_UPDATE':
            await self.handle_account_update(UpdateData.parse_obj(msg.get('balances', {})))
        else:
            logger.debug(f"Unhandled event type: {event_type}")

    async def handle_agg_trade(self, event: AggregatedTradeEvent):
        from flows.positions_flow import close_positions

        current_price = Decimal(event.price)
        old_pnl = self.state[event.symbol].pnl_diff

        pnl_diff = self.calculate_pnl(event.symbol, current_price)
        if pnl_diff > old_pnl:
            logger.warning(f"new_pnl:{event.symbol} - {pnl_diff} > {old_pnl}")
        self.state[event.symbol].pnl_diff = pnl_diff

        if pnl_diff > 0:
            logger.warning(f">> Close positions {event.symbol} by PNL: {pnl_diff} USDT")
            await close_positions(event.symbol)
            return None

        # Trailing logic
        await self.handle_trailing_long(event.symbol, current_price)

    async def handle_trailing_long(self, symbol, current_price):
        """
        Онлайн расчет трейлинга
        """
        position_long: BinancePosition = get_exist_position(
            symbol=symbol,
            position_side=OrderPositionSide.LONG,
        )

        if not position_long:
            return None

        trailing_2 = Decimal(position_long.webhook.settings.get('trail_2', 0))
        trailing_step = Decimal(position_long.webhook.settings.get('trail_step', 0))
        trailing_stop = position_long.activation_price * (1 - trailing_2 / 100)

        if current_price >= position_long.activation_price and self.state[symbol].long_trailing_price == Decimal(0):
            self.state[symbol].long_trailing_price = trailing_stop
            logger.warning(f"{symbol} -->TRAILING STOP ACTIVATED at: {round(trailing_stop, 8)}")
            await cancel_tp_order(symbol=symbol, webhook_id=position_long.webhook_id)
            logger.warning(f" -->Cancellation of TAKE PROFIT order: {symbol}")
        elif self.state[symbol].long_trailing_price != Decimal(0):

            if current_price >= self.state[symbol].long_trailing_price + (
                    self.state[symbol].long_trailing_price * Decimal(trailing_step) / 100):

                new_long_trailing_stop = current_price - (current_price * trailing_2 / 100)
                old_price = self.state[symbol].long_trailing_price
                percent_diff = (new_long_trailing_stop - old_price) / old_price * 100

                if percent_diff > 0.01:

                    logger.warning(
                        f"{symbol} percent diff: {round(percent_diff, 2)}")

                    self.state[symbol].long_trailing_price = new_long_trailing_stop
                    logger.warning(f"{symbol} -->Current price: {round(current_price, 8)}")
                    logger.warning(f"{symbol} -->TRAILING STOP price updated to: {round(new_long_trailing_stop, 8)}")

                    await check_closed_positions_status(symbol=symbol)
        else:

            if self.state[symbol].old_activation_price == 0:
                self.state[symbol].old_activation_price = position_long.activation_price
                logger.warning(
                    f"{symbol} -->Waiting for TRAILING STOP activation at the price of: {round(position_long.activation_price, 8)}")
            elif self.state[symbol].old_activation_price != 0 and self.state[symbol].old_activation_price != position_long.activation_price:
                self.state[symbol].old_activation_price = position_long.activation_price
                logger.warning(f"{symbol} -->Waiting for TRAILING STOP activation UPDATE price of: {round(position_long.activation_price, 8)}")

        if self.state[symbol].long_trailing_price and current_price <= self.state[symbol].long_trailing_price:
            from flows.positions_flow import close_positions

            logger.warning(f"--> Close positions {symbol} by LONG trailing, stop price: {round(current_price, 8)} ")

            await close_positions(symbol)
            self.state[symbol] = SymbolPositionState(
                long_trailing_price=0
            )

    async def handle_order_update(self, event: OrderTradeUpdate):
        if event.symbol not in self.symbols:
            return None

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

        logger.warning(f"Order: {event.order_status}, {event.order_type}")

        if event.order_status == 'FILLED':
            from flows.order_filled_flow import order_filled_flow
            await order_filled_flow(event=event, order_type=our_order_type)

        elif event.order_status == 'CANCELED':
            from flows.order_cancel_flow import order_cancel_flow
            await order_cancel_flow(event)
        elif event.order_status == 'REJECTED':
            pass
        elif event.order_status == 'EXPIRED':
            pass
        elif event.order_status == 'NEW':
            if our_order_type:
                from flows.order_new_flow import order_new_flow
                await order_new_flow(event, our_order_type)

    async def handle_account_update(self, event: UpdateData):
        if not event.positions:
            logger.warning("No positions found in account update")
            return None

        for position in event.positions:
            symbol = position.symbol
            await self.update_position(position, symbol)

    async def update_position(self, position_event: Position, symbol: str):
        position_side = OrderPositionSide.LONG if position_event.position_side == 'LONG' else OrderPositionSide.SHORT

        position: BinancePosition = get_exist_position(
            symbol=symbol,
            position_side=position_side,
            not_closed=False
        )

        if position_event.position_amount != 0 and not position:
            logger.warning(f"Open position in {symbol} with {position_event.position_amount} amount")
            open_position_task(
                symbol=symbol,
                position_qty=Decimal(abs(position_event.position_amount)),
                position_side=position_side,
                entry_price=Decimal(position_event.entry_price),
                entry_break_price=Decimal(position_event.breakeven_price)
            )

        elif position_event.position_amount == 0:
            logger.warning(f"Close position in {symbol} with {position_event.position_amount} amount")

            order_id = None

            # filled last order sell, sort desc
            for order in position.orders[::-1]:
                if order.status == OrderStatus.FILLED and order.side == OrderSide.BUY:
                    order_id = order.binance_id
                    break

            if order_id:
                pnl = get_position_closed_pnl(symbol=symbol)
            else:
                pnl = position_event.unrealized_pnl

            comission = self.__calculate_comission(position.orders)
            pnl -= comission

            close_position_task(
                position=position,
                pnl=round(pnl, 2),
                symbol=symbol,
                position_side=position_side
            )

            if symbol in self.state:
                self.state[symbol] = SymbolPositionState(
                    long_trailing_price=0 if position_side == OrderPositionSide.LONG else self.state[
                        symbol].long_trailing_price,
                    short_trailing_price=0 if position_side == OrderPositionSide.SHORT else self.state[
                        symbol].short_trailing_price,
                )

        else:
            logger.warning(
                f"Changed position in {symbol} from {position.position_qty} to {position_event.position_amount}")

            position.position_qty = Decimal(abs(position_event.position_amount))
            position.entry_price = Decimal(position_event.entry_price)
            position.entry_break_price = Decimal(position_event.breakeven_price)

            update_position_task(position=position)

    def __calculate_comission(self, orders: List[Order]):
        commission = sum(
            order.commission for order in orders if
            order.status == OrderStatus.FILLED and order.commission
        ) * 2
        return commission

    def calculate_pnl(self, symbol: str, current_price: Decimal):
        position_short = get_exist_position(
            symbol=symbol,
            position_side=OrderPositionSide.SHORT,
        )

        if position_short and position_short.position_qty != 0:
            position_long = get_exist_position(
                symbol=symbol,
                position_side=OrderPositionSide.LONG,
            )

            if not position_long:
                return 0

            commission_long = self.__calculate_comission(position_long.orders)
            commission_short = self.__calculate_comission(position_short.orders)

            if not position_long or not position_short:
                return 0

            long_pnl = (current_price - position_long.entry_price) * position_long.position_qty - commission_long
            short_pnl = (position_short.entry_price - current_price) * position_short.position_qty - commission_short

            if position_short and position_short.position_qty > 0:
                return round(long_pnl + short_pnl, 2)

        return 0

    def stop(self):
        """Stop all streams and cleanup"""
        logger.info("Stopping UNICORN WebSocket manager...")
        self.ubwa.stop_manager_with_all_streams()


async def start(symbols):
    """Main entry point"""
    trade_monitor = TradeMonitor(symbols)
    try:
        await trade_monitor.start_monitor()
    except KeyboardInterrupt:
        logger.info("Received interrupt signal")
    finally:
        trade_monitor.stop()


def main():
    asyncio.run(start(settings.SYMBOLS))


if __name__ == '__main__':
    main()
