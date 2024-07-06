from decimal import Decimal
import sys

from sqlmodel.ext.asyncio.session import AsyncSession

sys.path.append('../../core')
sys.path.append('')

from core.binance_futures import check_position
from core.schemas.position import LongPosition, ShortPosition
from core.schemas.webhook import WebhookPayload


def calculate_grid_orders(payload: WebhookPayload, initial_price: Decimal, fee_percentage: float = 0.2) -> dict:
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
    deposit = payload.settings.deposit
    leverage = payload.open.leverage

    # Расчет цены Take Profit ордера от открытия позиции
    take_profit_order_price = Decimal(initial_price) * Decimal(1 + (take_profit_percentage + Decimal(fee_percentage)) / 100)

    # Проверка корректности данных для количества шагов в сетке и количества ордеров
    if len(grid_long_steps) != order_quantity:
        raise ValueError("Количество данных в сетке не соответствует количеству ордеров order_quantity.")

    # Расчет цен лимитных ордеров для усреднения на лонг
    long_orders = [initial_price]
    for step in grid_long_steps:
        next_price = Decimal(long_orders[-1]) * Decimal(1 - step / 100)
        long_orders.append(next_price)

    # Удаление начальной цены, так как рассматриваются только усредняющие ордера
    long_orders = long_orders[1:]

    # Расчет цены лимитного ордера на шорт
    last_averaging_long_order_price = long_orders[-1]
    short_order_price = Decimal(last_averaging_long_order_price) * Decimal(1 - offset_short_percentage / 100)

    # Расчет стоп-лосса для короткой позиции
    stop_loss_short_order_price = Decimal(short_order_price) * Decimal(1 + stop_loss_short_percentage / 100)

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

    # Функция для проверки достаточности средств
    def is_sufficient_funds(initial_price, martingale_orders, max_deposit):
        total_cost = sum([initial_price * coins for coins in martingale_orders])
        return total_cost <= max_deposit

    # Проверка
    max_deposit = deposit * leverage
    sufficient_funds = is_sufficient_funds(initial_price, martingale_orders, max_deposit)
    total_cost = sum([initial_price * coins for coins in martingale_orders])

    # Формирование результата
    result = {
        "take_profit_order_price": take_profit_order_price,
        "long_orders": long_orders,
        "short_order_price": short_order_price,
        "short_order_amount": short_order_amount,
        "stop_loss_short_order_price": stop_loss_short_order_price,
        # считаем каждый раз после SHORT, после подтерждения что позиция открылась
        "martingale_orders": martingale_orders,
        "sufficient_funds": sufficient_funds,
        "total_cost": total_cost
    }

    return result


async def update_grid(
        payload: WebhookPayload,
):
    position_long, _ = await check_position(symbol=payload.symbol)
    position_long: LongPosition

    grid_orders = calculate_grid_orders(payload, position_long.markPrice)

    if grid_orders["sufficient_funds"] is False:
        raise ValueError("Недостаточно средств для открытия позиции.")

    return grid_orders
