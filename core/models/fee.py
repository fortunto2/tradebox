import requests
import hmac
import hashlib
import time

from config import get_settings


def get_commission_rates(symbol):
    settings = get_settings()

    api_key = settings.BINANCE_API_KEY
    secret_key = settings.BINANCE_API_SECRET

    base_url = 'https://fapi.binance.com'
    endpoint = '/fapi/v1/commissionRate'

    timestamp = int(time.time() * 1000)
    query_string = f'symbol={symbol}&timestamp={timestamp}'
    signature = hmac.new(secret_key.encode(), query_string.encode(), hashlib.sha256).hexdigest()

    headers = {
        'X-MBX-APIKEY': api_key
    }

    url = f'{base_url}{endpoint}?{query_string}&signature={signature}'

    response = requests.get(url, headers=headers)
    fees_info = response.json()

    maker_commission = float(fees_info['makerCommissionRate']) * 100
    taker_commission = float(fees_info['takerCommissionRate']) * 100

    return maker_commission, taker_commission

# передаем символ
# symbol = '1000PEPEUSDT'
# maker_commission, taker_commission = get_commission_rates(symbol)
#
# print(f"Maker Commission Rate: {maker_commission}%")  # для лимитных ордеров
# print(f"Taker Commission Rate: {taker_commission}%")  # для маркет ордеров
