from binance.cm_futures import CMFutures
import sys
sys.path.append('..')
sys.path.append('.')

from config import settings

client = CMFutures()
# get server time
print(client.time())
client = CMFutures(key=settings.BINANCE_API_KEY, secret=settings.BINANCE_API_SECRET)
# Get account information
print(client.account())
