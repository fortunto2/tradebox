from decimal import Decimal

from prefect import task

from core.clients.db_sync import execute_sqlmodel_query_single
from core.logger import logger
from core.models.binance_position import BinancePosition
from core.models.orders import OrderPositionSide, Order, OrderType
from core.schemas.webhook import WebhookPayload
from core.views.handle_orders import db_get_last_order
from core.views.handle_positions import get_exist_position, close_position_task
from flows.tasks.binance_futures import check_position, get_position_closed_pnl
from flows.tasks.orders_create import create_short_market_stop_order


async def check_closed_positions_status(symbol):
    """
    Это проверка при старте что у нас если на бирже позиции закрыты, то закрыть их и в базе
    todo: надо ли открывать позицию в базе если она есть на бирже а у нас нет?
    :param symbol:
    :return:
    """

    position_long, position_short = check_position(symbol)

    position_long_open_in_db: BinancePosition = get_exist_position(
        symbol=symbol,
        position_side=OrderPositionSide.LONG,
    )

    if position_long_open_in_db:
        if not position_long.positionAmt:
            logger.warning(f"no position in {symbol}")
            close_position_task(
                position=position_long_open_in_db,
            )

    position_short_open_in_db: BinancePosition = get_exist_position(
        symbol=symbol,
        position_side=OrderPositionSide.SHORT,
    )

    if position_short_open_in_db:
        if not position_short.positionAmt:
            logger.warning(f"no position in {symbol}")
            close_position_task(
                position=position_short_open_in_db
            )

    return position_long, position_short


@task
async def open_short_position_loop(
        payload: WebhookPayload,
        webhook_id,
        order_binance_id: str,
):

    pnl = get_position_closed_pnl(payload.symbol)
    print("pnl:", pnl)

    extramarg = Decimal(payload.settings.extramarg) - abs(pnl)

    if extramarg * Decimal(payload.open.leverage) < 11:
        # проверку что не extramarg не должен быть менее 11 долларов * плече
        print("Not enough money")
        return

    short_order: Order = execute_sqlmodel_query_single(
        lambda session: db_get_last_order(webhook_id, order_type=OrderType.SHORT_MARKET_STOP_OPEN, order_by='desc'))

    hedge_price = Decimal(short_order.price) * (1 - Decimal(payload.settings.offset_pluse) / 100)

    quantity = extramarg * Decimal(payload.open.leverage) / hedge_price

    # только один раз, когда хватает денег
    short_market_order = await create_short_market_stop_order(
        symbol=payload.symbol,
        price=hedge_price,
        quantity=quantity,
        leverage=payload.open.leverage,
        webhook_id=webhook_id,
    )
