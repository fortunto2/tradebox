# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Tradebox is a cryptocurrency trading bot for Binance Futures that implements automated grid trading strategies with webhooks from TradingView. The system manages long and short positions with averaging (martingale), take-profit orders, and trailing stop logic.

## Technology Stack

- **Framework**: FastAPI (async web server)
- **Database**: PostgreSQL (production) / SQLite (dev) with SQLModel ORM
- **Workflow Engine**: Prefect 2.x for orchestrating trading flows
- **Exchange**: Binance Futures API (binance-futures-connector, python-binance)
- **WebSocket**: Async real-time monitoring via binance library
- **Package Manager**: Poetry

## Architecture

### Core Components

1. **main.py** - FastAPI application with webhook endpoint and SQLAdmin interface
2. **ws_monitor_async.py** - WebSocket monitor that listens to Binance user data streams and aggregated trades
3. **flows/** - Prefect flows for position and order management
4. **core/** - Business logic, models, schemas, and database clients

### Data Flow

```
TradingView Webhook → FastAPI (/webhook) → open_long_position flow →
  → Market order execution → Grid order creation →
  → WebSocket monitors fills → Handles filled orders →
  → Creates averaging orders or closes position
```

### Key Models

- **WebHook**: Stores webhook configuration (symbol, leverage, grid settings, martingale steps)
- **BinancePosition**: Tracks open positions with entry price, activation price, PNL
- **Order**: Represents orders with types: LONG_MARKET, LONG_LIMIT, LONG_TAKE_PROFIT, SHORT_MARKET, SHORT_MARKET_STOP_OPEN, SHORT_MARKET_STOP_LOSS, SHORT_LIMIT
- **BinanceSymbol**: Stores symbol precision info for price/quantity adjustments

### Position Management Logic

The bot implements a hedging strategy:
1. Opens LONG position with market order
2. Creates grid of LONG limit orders (averaging down)
3. Creates SHORT hedge position when last averaging order is hit
4. Uses trailing stop logic to close positions in profit
5. Closes both LONG and SHORT when PNL target is reached

### WebSocket Monitor (ws_monitor_async.py)

Runs separately from the main API and handles:
- **aggTrade events**: Calculates real-time PNL and manages trailing stop
- **ORDER_TRADE_UPDATE**: Routes to flows based on order status (NEW, FILLED, CANCELED)
- **ACCOUNT_UPDATE**: Syncs positions from Binance to local DB

Key state tracked per symbol: `long_trailing_price`, `short_trailing_price`, `pnl_diff`, `old_activation_price`

**Connection Stability Features:**
- **Listen Key Keepalive**: BinanceSocketManager auto-refreshes every 30 minutes (configurable via `user_timeout`)
- **Exponential Backoff**: Retry delays increase from 3s to max 60s on connection failures
- **Timeout Detection**: 30-second timeout on recv() to detect dead connections
- **listenKeyExpired Handling**: Immediate reconnect when key expires
- **Queue Limits**: Message queue capped at 10,000 to prevent memory overflow
- **Error Isolation**: Individual message processing errors don't crash the monitor

### Grid Calculation (core/grid.py)

`calculate_grid_orders()` computes:
- Take-profit price from initial entry
- Grid of limit order prices using `grid_long` steps (percentage down from entry)
- Martingale quantities for each level using `mg_long` multipliers
- Validates sufficient funds based on `deposit * leverage`

### Order Processing Flows

- **order_new_flow**: Saves new orders from Binance to DB
- **order_filled_flow**: Main flow handling filled orders:
  - LONG_MARKET filled → creates TP order + first grid pair
  - LONG_LIMIT filled → creates new TP order + next grid pair
  - SHORT orders filled → creates stop-loss orders
- **order_cancel_flow**: Marks canceled orders in DB
- **positions_flow**: Opens/closes positions, cancels open orders

## Development Commands

### Setup

```bash
# Install dependencies
poetry install

# Run database migrations
make migrate-apply

# Create new migration
make migrate-create
```

### Running Locally

```bash
# Start FastAPI server
uvicorn main:app --reload --host 0.0.0.0 --port 8009

# Start WebSocket monitor (requires SYMBOLS env var)
python ws_monitor_async.py --symbols BTCUSDT,ETHUSDT

# Start Prefect server (optional, flows run inline now)
prefect server start
```

### Docker

```bash
# Build and run all services
docker compose up -d

# Restart backend after code changes
docker compose restart backend

# Update production (defined in Makefile)
make update
```

### Testing

```bash
# Run tests
pytest

# Run specific test
pytest tests/test_webhook.py -k test_name
```

## Database

### Connections

- Sync: Used by SQLAdmin and sync operations (core/clients/db_sync.py)
- Async: Used by FastAPI endpoints (core/clients/db_async.py)

### Migrations

Database migrations use Alembic. Models are imported in `migrations/env.py`:
- Order, WebHook, BinanceSymbol, BinancePosition

## Configuration

Environment variables (see config.py):
- `BINANCE_API_KEY`, `BINANCE_API_SECRET`: Binance credentials
- `DB_CONNECTION_STR`: PostgreSQL connection string
- `PREFECT_API_URL`: Prefect server URL
- `SYMBOLS`: Comma-separated list of trading symbols

## WebHook Payload Structure

Webhooks from TradingView must include:
- `symbol`: Trading pair (e.g., "BTCUSDT")
- `positionSide`: "LONG" or "SHORT"
- `side`: "BUY" or "SELL"
- `open.amount`: Initial order quantity
- `open.leverage`: Leverage (e.g., 5)
- `settings.order_quan`: Number of grid orders
- `settings.grid_long`: Array of grid steps (percentages)
- `settings.mg_long`: Array of martingale multipliers
- `settings.tp`: Take-profit percentage
- `settings.trail_1`, `settings.trail_2`, `settings.trail_step`: Trailing stop parameters
- `settings.offset_short`: Offset for SHORT hedge position
- `settings.sl_short`: Stop-loss for SHORT position
- `settings.deposit`: Available deposit amount

## Admin Interface

SQLAdmin is available at `/rust_admin` with views for:
- WebHooks (create webhook configs)
- BinanceSymbol (view symbol precisions)
- BinancePosition (view/edit positions)
- Orders (search and filter orders)

## Key Patterns

### Database Queries

Use `execute_sqlmodel_query` or `execute_sqlmodel_query_single` wrappers (core/clients/db_sync.py) for consistent session management.

### Prefect Tasks

Many functions are decorated with `@task` for Prefect tracking. Flows use `ConcurrentTaskRunner()` and `.submit()` for parallel execution.

### Error Handling

- Sentry SDK initialized for error tracking
- Custom exception handlers in main.py for validation and HTTP errors
- Binance API errors caught and returned as HTTPException

### Precision Adjustment

Use `BinanceSymbol.adjust_price()` and `adjust_quantity()` methods to round values to exchange precision requirements.

## Critical Notes

- **Dual Position Mode**: System requires Binance account in "Hedge Mode" (both LONG and SHORT positions open simultaneously)
- **WebSocket Separation**: ws_monitor_async.py must run separately from main API
- **Position Closing**: The `close_positions()` flow cancels all open orders first, then closes positions via market orders
- **Trailing Stop**: Managed in ws_monitor_async.py by tracking prices in memory, not via Binance trailing orders
- **Order Number**: Orders have `order_number` field for grid sequencing (0 = market entry, 1+ = grid levels)
- **Listen Key Expiration**: User data stream requires keepalive every 30-60 minutes or connection dies - handled automatically by BinanceSocketManager

## Troubleshooting WebSocket Disconnections

If ws_monitor loses connection, check logs for:
- `Listen key expired!` - keepalive not working, check Binance API permissions
- `No data from stream for 30s` - normal, automatic reconnect
- `Error in user data stream` with increasing retry delays - network or Binance API issues
- Queue full warnings - processing is too slow, check database or flow performance
