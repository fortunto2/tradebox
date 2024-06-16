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
