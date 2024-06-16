from binance.spot import Spot
from binance.websocket.spot.websocket_stream import SpotWebsocketStreamClient

from config import settings

# Binance API credentials (replace with your own)

client = Spot(api_key=settings.BINANCE_API_KEY, api_secret=settings.BINANCE_API_SECRET)

ws_client = SpotWebsocketStreamClient()
