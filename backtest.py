# https://github.com/Gunthersuper/Binance-Futures-Backtesting/tree/main
# pip install bokeh==3.1.0

from config import settings
from binance.client import Client
import pandas as pd

# Создаем клиента Binance
client = Client(
    api_key=settings.BINANCE_API_KEY,
    api_secret=settings.BINANCE_API_SECRET
)


from backtesting import Backtest, Strategy
from backtesting.lib import crossover


def get_historical_data(symbol: str, interval: str, start_str: str, limit=1000):
    klines = client.get_historical_klines(symbol, interval, start_str, limit=limit)
    df = pd.DataFrame(klines, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume',
                                       'close_time', 'quote_asset_volume', 'number_of_trades',
                                       'taker_buy_base_asset_volume', 'taker_buy_quote_asset_volume', 'ignore'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)
    df = df[['open', 'high', 'low', 'close', 'volume']]
    df = df.astype(float)

    # Переименовываем столбцы
    df.columns = ['Open', 'High', 'Low', 'Close', 'Volume']

    return df


# Получаем данные
data = get_historical_data('BTCUSDT', Client.KLINE_INTERVAL_1HOUR, "1 AUG 2024")

# Создаем стратегию
# Создаем стратегию
class CustomStrategy(Strategy):
    def init(self):
        self.orders_list = []
        self.pnl_list = []

    def next(self):
        current_price = self.data.Close[-1]

        if not self.position:
            if crossover(self.data.Close, self.data.Open):
                self.buy()
                self.orders_list.append({
                    'type': 'buy',
                    'price': current_price,
                    'time': self.data.index[-1]
                })

        else:
            if crossover(self.data.Open, self.data.Close):
                # Используем self.trades для получения цены входа
                entry_price = self.trades[-1].entry_price
                self.position.close()
                self.orders_list.append({
                    'type': 'sell',
                    'price': current_price,
                    'time': self.data.index[-1]
                })
                pnl = (current_price - entry_price) * self.trades[-1].size
                self.pnl_list.append(pnl)



# Запуск бэктеста с увеличенным капиталом
bt = Backtest(data, CustomStrategy,
              cash=1000000,  # Увеличиваем начальный капитал
              commission=.002,
              exclusive_orders=True)

output = bt.run()
plot = bt.plot()
