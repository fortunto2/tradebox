import json
from time import sleep

import sentry_sdk
from decimal import Decimal

from binance.websocket.um_futures.websocket_client import UMFuturesWebsocketClient
from sqlalchemy.orm import sessionmaker
from sqlmodel import create_engine, Session, select
from config import get_settings
from core.binance_futures import client, check_position, cancel_open_orders
from core.logger import logger
from core.models.orders import OrderStatus, Order, OrderSide, OrderType
from core.schemas.events.agg_trade import AggregatedTradeEvent
from core.schemas.events.order_trade_update import OrderTradeUpdate
from core.schemas.events.account_update import UpdateData
from core.schemas.webhook import WebhookPayload
from core.views.handle_orders import get_webhook_last, db_get_order_binance_id
from trade.orders.orders_create import create_short_stop_loss_order, create_long_market_order, \
    create_short_market_order, create_short_stop_order, create_long_tp_order
from trade.orders.orders_processing import check_orders_in_the_grid, grid_make_long_limit_order, \
    open_short_position_loop
from core.db_sync import execute_query, execute_query_single, execute_sqlmodel_query, execute_sqlmodel_query_single

settings = get_settings()

# Sentry Initialization
sentry_sdk.init(
    dsn="https://c167125710805940a14cc72b74bf2617@o103263.ingest.us.sentry.io/4507614078238720",
    traces_sample_rate=1.0,
    profiles_sample_rate=1.0,
)

# Create a synchronous SQLAlchemy engine
DATABASE_URL = settings.DB_ASYNC_CONNECTION_STR
engine = create_engine(DATABASE_URL, echo=settings.DEBUG, future=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

class TradeMonitor:
    def __init__(self, symbols):
        self.symbols = symbols
        self.long_position_qty = Decimal(0)
        self.long_entry_price = Decimal(0)
        self.short_position_qty = Decimal(0)
        self.short_entry_price = Decimal(0)
        self.client = UMFuturesWebsocketClient(on_message=self.on_message)
        self.long_pnl = 0
        self.short_pnl = 0

    def monitor_events(self):
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
                logger.warning(f"{symbol} -SHORT -> qty: {self.short_position_qty}, Entry price: {self.short_entry_price}")
            self.client.agg_trade(symbol)
        self.client.user_data(listen_key=listen_key)

    def on_message(self, ws, msg):
        try:
            message_dict = json.loads(msg)
            event_type = message_dict.get('e')
            if event_type == 'aggTrade':
                event = AggregatedTradeEvent.parse_obj(message_dict)
                self.handle_agg_trade(event)
            elif event_type == 'ORDER_TRADE_UPDATE':
                event = OrderTradeUpdate.parse_obj(message_dict.get('o'))
                self.handle_order_update(event)
            elif event_type == 'ACCOUNT_UPDATE':
                event = UpdateData.parse_obj(message_dict['a'])
                self.handle_account_update(event)
        except Exception as e:
            logger.error(f"Error in on_message: {e}", exc_info=True)
            sentry_sdk.capture_exception(e)

    def handle_agg_trade(self, event: AggregatedTradeEvent):
        try:
            trade_price = Decimal(event.price)
            self.long_pnl = 0
            if self.long_position_qty != 0:
                self.long_pnl = round((trade_price - self.long_entry_price) * self.long_position_qty, 2)
            if self.short_position_qty != 0:
                self.short_pnl = round((trade_price - self.short_entry_price) * self.short_position_qty, 2)
                _diff = round(self.long_pnl + self.short_pnl - Decimal(0.01), 2)
                if _diff > 0:
                    logger.warning(f"=Profit: {_diff} USDT")
                    status_cancel = cancel_open_orders(symbol=event.symbol)
                    with SessionLocal() as session:
                        webhook = get_webhook_last(event.symbol)
                        webhook_id = webhook.id
                        leverage = webhook.open.get('leverage', webhook.open['leverage'])
                        create_short_market_order(
                            symbol=event.symbol,
                            quantity=abs(self.short_position_qty),
                            leverage=leverage,
                            webhook_id=webhook_id,
                            side=OrderSide.BUY,
                        )
                        create_long_market_order(
                            symbol=event.symbol,
                            quantity=self.long_position_qty,
                            leverage=leverage,
                            webhook_id=webhook_id,
                            side=OrderSide.SELL,
                        )
                    logger.info(f">>> Cancel all open orders: {status_cancel}")
        except Exception as e:
            logger.error(f"Error in handle_agg_trade: {e}", exc_info=True)
            sentry_sdk.capture_exception(e)

    def handle_order_update(self, event: OrderTradeUpdate):
        # todo: add prefect
        try:
            with SessionLocal() as session:

                if event.symbol not in self.symbols:
                    return None

                if event.order_status == 'FILLED':

                    if event.order_type == 'MARKET':
                        logger.warning(f"Order Market Filled: {event.order_status}, {event.order_type}")
                        return None

                    logger.info(f"Order status: {event.order_status}")
                    order_binance_id = str(event.order_id)
                    logger.info(f"Order binance_id: {order_binance_id}")

                    timer = 0
                    # пока не поймем почему база тормозит или на префект не сделаем
                    # while timer < 3:
                    #
                    #     if not order:
                    #         timer += 1

                    order: Order = db_get_order_binance_id(order_binance_id)

                    if not order:
                        sleep(2)
                        order: Order = db_get_order_binance_id(order_binance_id)
                        if not order:
                            logger.error(f"!!!!!Order not found in DB - {order_binance_id}")
                            return None

                    webhook = get_webhook_last(event.symbol)
                    if not webhook:
                        logger.error(f"!!!!!Webhook not found in DB - {event.symbol}")
                        return None
                    # if event.side == 'SELL' and event.position_side == 'SHORT':
                    #     logger.warning(f"Create founded short_stop_order: {event.symbol}")
                    #     order = create_short_stop_order(
                    #         symbol=event.symbol,
                    #         price=Decimal(event.original_price),
                    #         quantity=Decimal(event.original_quantity),
                    #         leverage=webhook.open.get('leverage'),
                    #         webhook_id=webhook.id,
                    #     )
                    # elif event.side == 'BUY' and event.position_side == 'SHORT':
                    #     logger.warning(f"Create founded create_short_stop_loss_order: {event.symbol}")
                    #
                    #     order = create_short_stop_loss_order(
                    #         symbol=event.symbol,
                    #         sl_short=webhook.settings.get('sl_short'),
                    #         leverage=webhook.open.get('leverage'),
                    #         webhook_id=webhook.id,
                    #     )
                    # else:
                    #     return None
                    order.binance_id = order_binance_id
                    order.status = OrderStatus.FILLED
                    order.binance_status = event.order_status
                    session.add(order)
                    session.commit()

                    webhook = order.webhook
                    webhook_id = order.webhook.id

                    payload = WebhookPayload(
                        name=webhook.name,
                        side=order.side,
                        positionSide=order.position_side,
                        symbol=order.symbol,
                        open=webhook.open,
                        settings=webhook.settings
                    )
                    #
                    # if order.type == OrderType.LONG_MARKET or order.type == OrderType.SHORT_MARKET:
                    #     logger.warning(f"Order Market Filled: {event.order_status}, {order.type}")

                    if order.type == OrderType.LONG_TAKE_PROFIT:
                        status_cancel = cancel_open_orders(symbol=order.symbol)
                    elif order.type == OrderType.LONG_LIMIT:
                        logger.info(f"Order {order_binance_id} LIMIT start grid_make_limit_and_tp_order")
                        tp_order = create_long_tp_order(
                            symbol=payload.symbol,
                            tp=payload.settings.tp,
                            leverage=payload.open.leverage,
                            webhook_id=webhook_id,
                        )
                        filled_orders_in_db, grid_orders, grid = check_orders_in_the_grid(
                            payload, webhook_id)
                        if len(grid) >= len(filled_orders_in_db):
                            grid_make_long_limit_order(
                                webhook_id=webhook_id,
                                payload=payload
                            )
                        else:
                            logger.info(f"stop: filled_orders {filled_orders_in_db} >= grid_orders {grid_orders}")
                    elif order.type == OrderType.SHORT_STOP_LOSS:
                        logger.info(f"Order {order_binance_id} HEDGE_STOP_LOSS start make_hedge_by_pnl")
                        open_short_position_loop(
                            payload=payload,
                            webhook_id=order.webhook_id,
                            order_binance_id=order_binance_id,
                        )
                    elif order.type == OrderType.SHORT_LIMIT:
                        short_stop_loss_order = create_short_stop_loss_order(
                            symbol=payload.symbol,
                            sl_short=payload.settings.sl_short,
                            leverage=payload.open.leverage,
                            webhook_id=order.webhook_id
                        )
                        logger.info(f"Create short_stop_loss_order: {short_stop_loss_order.id}")
                    session.commit()
        except Exception as e:
            logger.error(f"Error in handle_order_update: {e}", exc_info=True)
            sentry_sdk.capture_exception(e)

    def handle_account_update(self, event: UpdateData):
        for position in event.positions:
            if position.position_side == 'LONG':
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
@click.option("--symbol", prompt="Symbol", default="UNFIUSDT", show_default=True,
              help="Enter the trading symbol (default: UNFIUSDT)")
def main(symbol):
    check_orders([symbol])
    trade_monitor = TradeMonitor([symbol])
    trade_monitor.monitor_events()


if __name__ == '__main__':
    main()
