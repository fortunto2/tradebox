import time
from decimal import Decimal
from typing import List

from core.binance_futures import get_position_closed_pnl, check_position, check_all_orders, wait_order_id
from core.models.orders import OrderType, OrderStatus, OrderPositionSide, OrderSide, OrderBinanceStatus, Order
from core.schemas.webhook import WebhookPayload
from core.views.handle_orders import db_get_last_order, db_get_orders
from trade.orders.grid import update_grid
from trade.orders.orders_create import create_long_market_order, create_long_tp_order, create_long_limit_order, create_short_stop_order
from core.db_sync import execute_sqlmodel_query, execute_sqlmodel_query_single


def open_long_position(payload: WebhookPayload, webhook_id):
    first_order = create_long_market_order(
        symbol=payload.symbol,
        quantity=payload.open.amount,
        leverage=payload.open.leverage,
        webhook_id=webhook_id,
    )

    tp_order = create_long_tp_order(
        symbol=payload.symbol,
        tp=payload.settings.tp,
        leverage=payload.open.leverage,
        webhook_id=webhook_id,
    )

    # первый запуск создание пары ордеров лимитных по сетке
    grid_make_long_limit_order(
        webhook_id=webhook_id,
        payload=payload,
    )

    return


def open_short_position_loop(
        payload: WebhookPayload,
        webhook_id,
        order_binance_id: str,
):
    extramarg = Decimal(payload.settings.extramarg)

    # quantity - в цикле уменьшеается, вычитаем убытки

    pnl = get_position_closed_pnl(payload.symbol, int(order_binance_id))
    print("pnl:", pnl)

    extramarg = Decimal(payload.settings.extramarg) + pnl

    if extramarg * Decimal(payload.open.leverage) < 11:
        # проверку что не extramarg не должен быть менее 11 долларов * плече
        print("Not enough money")
        return

    short_order: Order = execute_sqlmodel_query_single(lambda session: db_get_last_order(webhook_id, order_type=OrderType.SHORT_LIMIT, order_by='ask'))

    hedge_price = Decimal(short_order.price) * (1 - Decimal(payload.settings.offset_pluse) / 100)

    quantity = extramarg * Decimal(payload.open.leverage) / hedge_price

    # только один раз, когда хватает денег
    hedge_stop_order = create_short_stop_order(
        symbol=payload.symbol,
        price=hedge_price,
        quantity=quantity,
        leverage=payload.open.leverage,
        webhook_id=webhook_id,
    )

    return hedge_stop_order.binance_id


def get_grid_orders(
        symbol: str,
        status: OrderStatus = OrderStatus.FILLED,
        webhook_id=None,
) -> List[Order]:
    """
    Ищем в базе все ордера которые уже исполнились из сетки и сверяем статусы с бинанс.

    OrderPositionSide.LONG,
    side=OrderSide.BUY,
    type=OrderType.LIMIT,

    :param symbol:
    :param status:
    :param webhook_id:
    :return:
    """
    def get_orders(session):
        if webhook_id:
            orders = db_get_orders(
                webhook_id=webhook_id,
                order_status=status,
                position_side=OrderPositionSide.LONG,
                order_type=OrderType.LONG_LIMIT,
                order_side=OrderSide.BUY,
            )
        else:
            orders = db_get_orders(
                order_status=status,
                position_side=OrderPositionSide.LONG,
                order_type=OrderType.LONG_LIMIT,
                order_side=OrderSide.BUY,
            )
        return orders

    return execute_sqlmodel_query(get_orders)


def check_orders_in_the_grid(payload: WebhookPayload, webhook_id):
    def check_orders(session):
        grid_orders = update_grid(payload, webhook_id)

        grid = list(zip(grid_orders["long_orders"], grid_orders["martingale_orders"]))
        print(f"grid_orders: {len(grid)}")

        filled_orders = get_grid_orders(
            symbol=payload.symbol,
            status=OrderStatus.FILLED,
            webhook_id=webhook_id,
        )

        print(f"filled_orders: {len(filled_orders)}")

        return filled_orders, grid_orders, grid

    return execute_sqlmodel_query(check_orders)


def grid_make_long_limit_order(
        webhook_id,
        payload: WebhookPayload):
    """
    :param payload:
    :param webhook_id:
    :return: Вернет True если есть еще ордера в сетке, False если последний ордер
    """
    def create_limit_order(session):
        if not payload:
            print("payload not found, webhook_id:", webhook_id)
            return False

        filled_orders, grid_orders, grid = check_orders_in_the_grid(payload, webhook_id)

        price, quantity = grid[len(filled_orders)]

        limit_order = create_long_limit_order(
            symbol=payload.symbol,
            price=price,
            quantity=quantity,
            leverage=payload.open.leverage,
            webhook_id=webhook_id,
        )

        if len(filled_orders) == len(grid) - 1:
            short_order_price = Decimal(price) * Decimal(1 - payload.settings.offset_short / 100)
            short_order_amount = Decimal(payload.settings.extramarg * payload.open.leverage) / short_order_price

            time.sleep(0.5)

            create_short_stop_order(
                symbol=payload.symbol,
                price=short_order_price,
                quantity=short_order_amount,
                leverage=payload.open.leverage,
                webhook_id=webhook_id,
            )

        session.commit()

        return True

    return execute_sqlmodel_query(create_limit_order)


def wait_limit_order_filled(symbol, order_id):
    wait_order_id(
        symbol=symbol,
        order_id=order_id
    )


def main():
    orders = get_grid_orders("JOEUSDT", OrderStatus.FILLED, 7)
    print(orders)


if __name__ == "__main__":
    main()
