from decimal import Decimal
from prefect import flow, tags, get_run_logger
from prefect.task_runners import ConcurrentTaskRunner

from core.logger import logger
from core.models.binance_position import PositionStatus, BinancePosition
from core.schemas.position import LongPosition, ShortPosition
from core.views.handle_positions import close_position_task, get_exist_position
from flows.tasks.binance_futures import cancel_open_orders, check_position
from core.models.orders import OrderSide, OrderPositionSide
from flows.tasks.orders_create import create_short_market_order, create_long_market_order


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


@flow(task_runner=ConcurrentTaskRunner())
async def close_positions(symbol: str, close_short=True, close_long=True):

    with tags(symbol):
        logger = get_run_logger()

        status_cancel = cancel_open_orders(symbol=symbol)

        logger.info(f">>> Cancel all open orders: {status_cancel}")

        position_long, position_short = check_position(symbol=symbol)
        position_long: LongPosition
        position_short: ShortPosition

        # -- LONG ----------
        if abs(position_long.positionAmt) > 0 and close_long:
            create_long_market_order(
                symbol=symbol,
                quantity=abs(position_long.positionAmt),
                side=OrderSide.SELL
            )

        # -- Short----------
        if abs(position_short.positionAmt) > 0 and close_short:

            create_short_market_order(
                symbol=symbol,
                quantity=abs(position_short.positionAmt),
                side=OrderSide.BUY
            )

        return True
