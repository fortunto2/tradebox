from decimal import Decimal

from binance.websocket.um_futures.websocket_client import UMFuturesWebsocketClient


class TradeMonitorBase:
    def __init__(self, symbols):
        self.symbols = symbols
        self.long_position_qty = Decimal(0)
        self.long_entry_price = Decimal(0)
        self.short_position_qty = Decimal(0)
        self.short_entry_price = Decimal(0)
        self.client = UMFuturesWebsocketClient(on_message=self.on_message)
        self.long_pnl = 0
        self.short_pnl = 0
