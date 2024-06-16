from functools import lru_cache

from binance.um_futures import UMFutures
import sys

sys.path.append('..')
sys.path.append('.')

from config import settings

client = UMFutures()
# get server time
print(client.time())
client = UMFutures(key=settings.BINANCE_API_KEY, secret=settings.BINANCE_API_SECRET)
# Get account information
print(client.account())


@lru_cache()
def get_symbol_info(symbol):
    exchange_info = client.exchange_info()
    for s in exchange_info['symbols']:
        if s['symbol'] == symbol:
            return s
    return None


from decimal import Decimal, ROUND_DOWN


def adjust_precision(value, precision):
    quantize_str = '1.' + '0' * precision
    return value.quantize(Decimal(quantize_str), rounding=ROUND_DOWN)


@lru_cache()
def get_symbol_price_and_quantity_by_precisions(symbol, quantity):
    symbol_info = get_symbol_info(symbol)
    if not symbol_info:
        raise ValueError(f"Symbol {symbol} not found in exchange info")

    for filter in symbol_info['filters']:
        if filter['filterType'] == 'LOT_SIZE':
            quantity_precision = int(filter['stepSize'].find('1') - 1)
        if filter['filterType'] == 'PRICE_FILTER':
            price_precision = int(filter['tickSize'].find('1') - 1)

        print("quantity_precision: ", quantity_precision)
        print("price_precision : ", price_precision)

    price = client.ticker_price(symbol)
    print(price)

    # Приведение quantity и price к Decimal и корректировка точности
    quantity = adjust_precision(Decimal(quantity), quantity_precision)
    price = adjust_precision(Decimal(price), price_precision)

    return quantity, price


if __name__ == "__main__":
    print(get_symbol_price_and_quantity_by_precisions("JOEUSDT", 0.0001))
    print(get_symbol_price_and_quantity_by_precisions("JOEUSDT", 0.00000001))
    print(get_symbol_price_and_quantity_by_precisions("JOEUSDT", 60))
