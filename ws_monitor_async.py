import asyncio
from asyncio import sleep
from typing import List, Dict
from decimal import Decimal
import json

import sentry_sdk
from binance import AsyncClient, BinanceSocketManager
from binance.exceptions import BinanceAPIException
from pydantic import BaseModel, Field

from core.models.binance_position import PositionStatus, BinancePosition
from core.models.orders import OrderType, OrderPositionSide, Order, OrderStatus
from core.schemas.events.agg_trade import AggregatedTradeEvent
from core.schemas.events.base import Position
from core.schemas.events.order_trade_update import OrderTradeUpdate
from core.schemas.events.account_update import UpdateData
from config import get_settings
from core.views.handle_positions import get_exist_position, close_position_task, update_position_task, \
    open_position_task
from flows.order_new_flow import order_new_flow
from core.logger import logger
from flows.agg_trade_flow import close_positions, check_closed_positions_status
from flows.order_filled_flow import order_filled_flow
from flows.order_cancel_flow import order_cancel_flow

settings = get_settings()

sentry_sdk.init(
    dsn="https://c167125710805940a14cc72b74bf2617@o103263.ingest.us.sentry.io/4507614078238720",
    traces_sample_rate=1.0,
    profiles_sample_rate=1.0,
)

class SymbolPositionState(BaseModel):
    """
    Состояние различных переменных кешируем по символу для работы в вебсокетах без базы
    """
    long_trailing_price: Decimal = Field(default_factory=lambda: Decimal(0))
    short_trailing_price: Decimal = Field(default_factory=lambda: Decimal(0))


class TradeMonitor:
    def __init__(self, client: AsyncClient, symbols: List[str]):
        self.client = client
        self.bsm = BinanceSocketManager(client)

        self.symbols = symbols
        self.state: Dict[str, SymbolPositionState] = {symbol: SymbolPositionState() for symbol in symbols}

    async def start_monitor_events(self):
        while True:
            try:
                tasks = [self.monitor_symbol(symbol) for symbol in self.symbols]
                tasks.append(self.monitor_user_data())  # Добавляем задачу для мониторинга пользовательских данных
                await asyncio.gather(*tasks)
            except Exception as e:
                logger.error(f"Error in monitor events: {e}")
            # finally:
            #     logger.info("Reconnecting to the WebSocket in 1 seconds...")
            #     await asyncio.sleep(1)

    async def monitor_symbol(self, symbol: str):
        """
        https://developers.binance.com/docs/binance-spot-api-docs/web-socket-streams
        :param symbol:
        :return:
        """
        await check_closed_positions_status(symbol)

        streams = [
            f'{symbol.lower()}@aggTrade',  # Stream для агрегированных торгов
        ]
        async with self.bsm.futures_multiplex_socket(streams) as stream:
            while True:
                msg = await stream.recv()
                if msg:
                    await self.on_message(msg.get('data'))

    async def monitor_user_data(self):

       async with self.bsm.futures_user_socket() as user_stream:
            while True:
                user_msg = await user_stream.recv()
                if user_msg:
                    await self.on_message(user_msg)

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

        current_price = Decimal(event.price)

        pnl_diff = self.calculate_pnl(event.symbol, current_price)

        if pnl_diff > 0:
            logger.warning(f"={event.symbol} Profit: {pnl_diff} USDT")
            await close_positions(event.symbol)
            return None

        # Trailing logic (asynchronous)
        await self.handle_trailing_long(event.symbol, current_price)

    async def handle_trailing_long(self, symbol, current_price):
        """
        Онлайн расчет трейлинга
        :param symbol:
        :param current_price:
        :return:
        """

        # todo: придумать чтоб каждый раз позицию из базы не дергал
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
        elif self.state[symbol].long_trailing_price != Decimal(0):

            if current_price >= self.state[symbol].long_trailing_price + (self.state[symbol].long_trailing_price * Decimal(trailing_step) / 100):

                new_long_trailing_stop = current_price - (current_price * trailing_2 / 100)

                if new_long_trailing_stop > self.state[symbol].long_trailing_price:
                    old_price = self.state[symbol].long_trailing_price

                    logger.warning(f"{symbol} percent diff: {round((new_long_trailing_stop - old_price) / old_price * 100, 2)}")

                    self.state[symbol].long_trailing_price = new_long_trailing_stop
                    logger.warning(f"{symbol} Current price: {round(current_price, 8)}")
                    logger.warning(f"{symbol} Trailing stop updated to: {round(new_long_trailing_stop, 8)}")

                    await check_closed_positions_status(symbol=symbol)

        if self.state[symbol].long_trailing_price and current_price <= self.state[symbol].long_trailing_price:
            logger.warning(f"{symbol} Trailing stop triggered at: {round(current_price, 8)}")
            await close_positions(symbol)
            self.state[symbol] = SymbolPositionState(
                long_trailing_price=0
            )
            await sleep(3) # todo: позиция не успевает в базе закрыться, надо дать время, чтоб заново не начился трейлинг

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
            filled_order = await order_filled_flow(event=event, order_type=our_order_type)
            if not filled_order:
                await order_new_flow(event, our_order_type)
        elif event.order_status == 'CANCELED':
            await order_cancel_flow(event)
        elif event.order_status == 'REJECTED':
            pass
        elif event.order_status == 'EXPIRED':
            pass
        elif event.order_status == 'NEW':
            if our_order_type:
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

            # уже закрываем во флоу close_positions
            close_position_task(
                position=position,
                pnl=position_event.unrealized_pnl,
                symbol=symbol,
                position_side=position_side
            )

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

            update_position_task(
                position=position
            )

        # await check_closed_positions_status(symbol=symbol)

    def calculate_pnl(self, symbol: str, current_price: Decimal):

        # todo вебхук бы сразу знать или айди позиции
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

            commission_long = sum(
                order.commission for order in position_long.orders if
                order.status == OrderStatus.FILLED and order.commission
            ) * 2

            commission_short = sum(
                order.commission for order in position_short.orders if
                order.status == OrderStatus.FILLED and order.commission
            ) * 2

            if not position_long or not position_short:
                return 0

            long_pnl = (current_price - position_long.entry_price) * position_long.position_qty - commission_long
            short_pnl = (position_short.entry_price - current_price) * position_short.position_qty - commission_short

            # Если есть шортовая позиция, закрываем по маркету только если она существует и PnL положительный
            if position_short and position_short.position_qty > 0:
                return round(long_pnl + short_pnl, 2)

        return 0


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
