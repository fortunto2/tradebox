from decimal import Decimal
from core.schemas.webhook import WebhookPayload



# def adjust_trade_parameters(payload: WebhookPayload, initial_price: Decimal):
#     calculate_entry_price_start = Decimal(payload.open.entry_price)
#     take_profit_percentage = payload.settings.tp
#     trailing_1 = Decimal(payload.settings.get('trail_1', 0))

def adjust_trade_parameters(initial_price, calculate_entry_price_start, take_profit_percentage, trailing_1):
    """
    Корректирует процент тейк-профита и уровень трейлинга в зависимости от разницы между фактической и расчетной ценой открытия позиции.
    """
    # Рассчитываем процентное отклонение между фактической и расчетной ценой открытия
    price_difference_percentage = ((initial_price - calculate_entry_price_start) / calculate_entry_price_start) * Decimal(100)

    # Корректируем процент TP, учитывая разницу в цене
    adjusted_take_profit_percentage = round(take_profit_percentage - price_difference_percentage, 2)

    # Корректируем уровень трейлинга, учитывая разницу в цене
    adjusted_trail_1 = round(trailing_1 - price_difference_percentage, 2)

    print(f"Скорректированный процент тейк-профита: {adjusted_take_profit_percentage}%")
    print(f"Скорректированный уровень трейлинга (trailing_1): {adjusted_trail_1}%")

    return adjusted_take_profit_percentage, adjusted_trail_1


# Пример
initial_price = Decimal("0.14508")                  # Цена фактического открытия
calculate_entry_price_start = Decimal("0.14507")    # Цена расчетного открытия
take_profit_percentage = Decimal("1.28")            # Процент TP, полученный по вебхуку
trailing_1 = Decimal("0.73")                           # Текущий уровень трейлинга, полученный по вебхуку

adjusted_tp_percentage, adjusted_trail_1 = adjust_trade_parameters(
    initial_price, calculate_entry_price_start, take_profit_percentage, trailing_1
)

print(f"Скорректированный процент тейк-профита: {adjusted_tp_percentage}%")
print(f"Скорректированный уровень трейлинга (trail_1): {adjusted_trail_1}%")

