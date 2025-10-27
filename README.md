# Tradebox

A cryptocurrency trading bot for Binance Futures that implements automated grid trading strategies with webhooks from TradingView.

## Overview

Tradebox is an async trading bot that manages long and short positions with:
- **Grid Trading**: Automated averaging orders at multiple price levels
- **Take-Profit Management**: Closing positions at target profit levels
- **Trailing Stop Logic**: Dynamic stop-loss management via WebSocket monitoring
- **Hedge Strategy**: Simultaneous LONG and SHORT positions for risk management

## Technology Stack

- **Framework**: FastAPI (async REST API)
- **Database**: PostgreSQL (production) / SQLite (development) with SQLModel ORM
- **Workflow Engine**: Prefect 2.x for orchestrating trading flows
- **WebSocket**: Unicorn Binance WebSocket API for real-time monitoring
- **Exchange**: Binance Futures API
- **Package Manager**: uv

## Quick Start

### Prerequisites

- Python 3.10+ (tested with 3.13)
- PostgreSQL or SQLite
- Binance Futures account in Hedge Mode
- Binance API credentials (key + secret)

### Installation

```bash
# Install dependencies
uv sync

# Create environment file
cp .env.example .env

# Configure your Binance API credentials in .env
```

### Running

```bash
# Start FastAPI server
uv run uvicorn main:app --reload --host 0.0.0.0 --port 8009

# In another terminal, start WebSocket monitor
uv run python ws_monitor_async.py --symbols BTCUSDT,ETHUSDT

# Access admin panel
# http://localhost:8009/rust_admin
```

## Architecture

### Core Components

1. **main.py** - FastAPI application with:
   - Webhook endpoint for TradingView signals
   - SQLAdmin interface for configuration
   - Position and order management endpoints

2. **ws_monitor_async.py** - WebSocket monitor that:
   - Listens to Binance user data streams
   - Calculates real-time PNL
   - Manages trailing stop logic
   - Routes filled orders to processing flows

3. **flows/** - Prefect flows for:
   - Position opening/closing
   - Order creation and management
   - Grid calculation and averaging

4. **core/** - Business logic:
   - Database clients and models
   - Grid calculation algorithms
   - Binance API integration

### Trading Flow

```
TradingView Webhook
    ↓
FastAPI /webhook endpoint
    ↓
open_long_position flow
    ↓
Market order execution
    ↓
Grid order creation
    ↓
WebSocket monitors fills
    ↓
Averaging or close position
```

## Configuration

### Environment Variables

Required:
- `BINANCE_API_KEY` - Binance API key
- `BINANCE_API_SECRET` - Binance API secret
- `DB_CONNECTION_STR` - Database URL

Optional:
- `PREFECT_API_URL` - Prefect server URL (default: http://127.0.0.1:4200/api)
- `SYMBOLS` - Comma-separated trading symbols (e.g., BTCUSDT,ETHUSDT)

### Webhook Payload

TradingView webhooks must include:

```json
{
  "symbol": "BTCUSDT",
  "positionSide": "LONG",
  "side": "BUY",
  "open.amount": 0.5,
  "open.leverage": 5,
  "settings.order_quan": 5,
  "settings.grid_long": [0.5, 1.0, 1.5, 2.0, 2.5],
  "settings.mg_long": [1, 1.5, 2, 2.5, 3],
  "settings.tp": 2.5,
  "settings.trail_1": 0.5,
  "settings.trail_2": 0.3,
  "settings.trail_step": 0.1,
  "settings.offset_short": 0.2,
  "settings.sl_short": -2.0,
  "settings.deposit": 1000
}
```

## Database

### Setup

```bash
# Run migrations
uv run alembic upgrade head

# Create new migration
uv run alembic revision --autogenerate -m "description"
```

### Models

- **WebHook** - Trading strategy configuration
- **BinancePosition** - Open position tracking
- **Order** - Order management (LONG/SHORT, MARKET/LIMIT/TP/SL)
- **BinanceSymbol** - Symbol precision information

## Admin Interface

Access SQLAdmin at `/rust_admin` to:
- Create and manage webhook configurations
- View and edit open positions
- Monitor orders and fills
- View symbol precision settings

## Key Features

### Position Management
- Hedge mode support (simultaneous LONG and SHORT)
- Averaging at multiple grid levels
- Take-profit order creation on market fill
- Automatic position closing on target profit

### Order Handling
- Market orders for position entry
- Grid limit orders for averaging
- Stop-loss orders for risk management
- Take-profit orders for exit

### WebSocket Monitoring
- Real-time aggTrade events for PNL calculation
- ORDER_TRADE_UPDATE for fill processing
- ACCOUNT_UPDATE for position synchronization
- Automatic listen key keepalive (every 30 minutes)
- Exponential backoff on connection failures

### Trailing Stop
- Dynamic trailing based on price movements
- Managed in-memory per symbol
- Configurable trail start and step

## Development

### Running Tests

```bash
uv run pytest
uv run pytest tests/test_webhook.py -k test_name
```

### Database Migrations

```bash
# Run all pending migrations
uv run alembic upgrade head

# Rollback one migration
uv run alembic downgrade -1
```

### Docker (Optional)

```bash
# Build and run all services
docker compose up -d

# Restart backend after changes
docker compose restart backend
```

## Critical Notes

- **Binance Hedge Mode Required**: Account must be in "Hedge Mode" to run simultaneous LONG and SHORT positions
- **WebSocket Separation**: ws_monitor_async.py must run separately from the FastAPI server
- **Listen Key Expiration**: User data streams require keepalive every 30-60 minutes
- **Precision Adjustment**: All orders are adjusted to exchange precision requirements
- **Order Numbering**: Grid orders have `order_number` field (0 = market, 1+ = grid levels)

## Troubleshooting

### WebSocket Connection Issues

If ws_monitor loses connection, check logs for:
- `Listen key expired!` - Keepalive issue, check Binance API permissions
- `No data from stream for 30s` - Normal, automatic reconnect
- `Error in user data stream` - Network or API issues, check retry delays

### Build Issues with Python 3.14

If you encounter Cython compilation errors:
1. Use Python 3.13 instead: `uv sync --python 3.13`
2. Or downgrade unicorn-binance-websocket-api to 1.46.x

## License

MIT

## Support

For issues, questions, or contributions, please open an issue on GitHub.

## References

- [Binance Futures API Documentation](https://binance-docs.github.io/apidocs/)
- [TradingView Webhook Documentation](https://www.tradingview.com/support/solutions/43000529348-webhooks/)
- [Prefect Documentation](https://docs.prefect.io/)
