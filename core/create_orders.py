import json
from decimal import Decimal
import sys
from pprint import pprint

from sqlalchemy import create_engine
from sqlmodel import SQLModel

sys.path.append('..')
sys.path.append('.')

from core.db_async import async_engine
from sqlalchemy.ext.asyncio import AsyncSession

from core.models.orders import Order, PositionSide
from core.schema import WebhookPayload


def calculate_orders(payload: WebhookPayload, initial_price: Decimal, fee_percentage: float = 0.2) -> dict:
    """
    Calculates various order prices based on the provided webhook payload and initial price.

    :param payload: WebhookPayload object containing the settings and open order information
    :param initial_price: Initial price from the exchange
    :param fee_percentage: Percentage fee for the transaction, default is 0.2%
    :return: Dictionary containing calculated prices and orders
    """
    order_quantity = payload.settings.order_quan  # Количество ордеров - получено из webhook
    offset_short_percentage = payload.settings.offset_short
    take_profit_percentage = payload.settings.tp
    stop_loss_short_percentage = payload.settings.sl_short
    grid_long_steps = payload.settings.grid_long
    initial_coins_quantity = payload.open.amount
    martingale_steps = payload.settings.mg_long

    # Расчет цены Take Profit ордера от открытия позиции
    take_profit_order_price = initial_price * Decimal(1 + (take_profit_percentage + fee_percentage) / 100)

    # Проверка корректности данных для количества шагов в сетке и количества ордеров
    if len(grid_long_steps) != order_quantity:
        raise ValueError("Количество данных в сетке не соответствует количеству ордеров order_quantity.")

    # Расчет цен лимитных ордеров для усреднения на лонг
    long_orders = [initial_price]
    for step in grid_long_steps:
        next_price = long_orders[-1] * Decimal(1 - step / 100)
        long_orders.append(next_price)

    # Удаление начальной цены, так как рассматриваются только усредняющие ордера
    long_orders = long_orders[1:]

    # Расчет цены лимитного ордера на шорт
    last_averaging_long_order_price = long_orders[-1]
    short_order_price = last_averaging_long_order_price * Decimal(1 - offset_short_percentage / 100)

    # Расчет стоп-лосса для короткой позиции
    stop_loss_short_order_price = short_order_price * Decimal(1 + stop_loss_short_percentage / 100)

    short_order_amount = Decimal(payload.settings.extramarg * payload.open.leverage) / short_order_price

    # Проверка корректности данных для количества шагов Мартингейла и количества ордеров
    if len(martingale_steps) != order_quantity:
        raise ValueError("Количество данных в шагах Мартингейла не соответствует количеству ордеров order_quantity.")

    # Расчет количества монет по стратегии Мартингейла
    martingale_orders = [initial_coins_quantity]
    for step in martingale_steps:
        next_coins_quantity = martingale_orders[-1] + (martingale_orders[-1] * Decimal(step / 100))
        martingale_orders.append(next_coins_quantity)

    # Удаление начального количества монет, так как интересуют только результаты после первого шага
    martingale_orders = martingale_orders[1:]

    # Формирование результата
    result = {
        "take_profit_order_price": take_profit_order_price,
        "long_orders": long_orders,
        "short_order_price": short_order_price,
        "short_order_amount": short_order_amount,
        "stop_loss_short_order_price": stop_loss_short_order_price, #считаем каждый раз после SHORT, после подтерждения что позиция открылась
        "martingale_orders": martingale_orders
    }

    return result


async def create_orders_in_db(payload: WebhookPayload, current_price: Decimal, session: AsyncSession):
    orders = calculate_orders(payload, current_price)

    print(orders)

    # Создание ордеров и запись в базу данных
    for price, quantity in zip(orders["long_orders"], orders["martingale_orders"]):
        print("-----------------")

        order = Order(
            symbol=payload.symbol,
            side=payload.side,
            price=price,
            quantity=quantity,
            leverage=payload.open.leverage,
            position_side=PositionSide.LONG
        )
        pprint(order.model_dump())
        session.add(order)

    short_order = Order(
        symbol=payload.symbol,
        side="SELL",
        price=orders["short_order_price"],
        quantity=orders["short_order_amount"],
        leverage=payload.open.leverage,
        position_side=PositionSide.SHORT
    )

    pprint(short_order.model_dump())
    session.add(short_order)

    await session.commit()
    return orders


async def main(payload: WebhookPayload, current_price: Decimal = Decimal(0.3634)):
    async with async_engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    async with AsyncSession(async_engine) as session:
        await create_orders_in_db(payload, current_price, session)


if __name__ == "__main__":
    import sys

    sys.path.append('..')
    sys.path.append('.')

    with open('tests/joe.json', 'r') as file:
        data = json.load(file)

    payload = WebhookPayload(**data)

    # result = calculate_orders(payload, Decimal(0.3634))
    # print(result)

    import asyncio

    # from core.db_async import async_session
    asyncio.run(main(payload, Decimal(0.3634)))
