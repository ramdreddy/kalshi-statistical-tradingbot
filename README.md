# Kalshi Statistical Trading Bot

Async, event-driven Python framework for trading Kalshi weather prediction markets.

**Repository:** https://github.com/ramdreddy/kalshi-statistical-tradingbot The codebase separates configuration, domain models, market data feeds, exchange connectivity, strategy plugins, and the runtime engine.

## Repository layout

```
kalshi-weather-bot/
├── src/kalshi_bot/
│   ├── config.py              # Environment-based settings
│   ├── main.py                # Asyncio entrypoint
│   ├── domain/                # Shared models and events
│   ├── strategies/            # BaseStrategy + implementations
│   ├── feeds/                 # WeatherFeeder (dummy metrics)
│   ├── exchange/              # Mock Kalshi order-book WebSocket
│   └── engine/                # Event bus and TradingEngine
├── tests/
├── .env.example
└── pyproject.toml
```

## Quick start

```bash
cd kalshi-weather-bot
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
python -m kalshi_bot
```

Press `Ctrl+C` to stop. With default settings the bot runs in mock mode: `WeatherFeeder` emits synthetic weather readings and `MockKalshiOrderBookWebSocket` streams fake order-book snapshots. `WeatherImbalanceStrategy` calls `evaluate_imbalance` on each update and logs signals when edge exceeds the configured threshold.

## Configuration

All runtime options are loaded from environment variables (see `.env.example`). Pydantic Settings also reads a local `.env` file if present.

| Variable | Description |
|----------|-------------|
| `KALSHI_MARKET_TICKER` | Target contract ticker |
| `WEATHER_POLL_INTERVAL_SEC` | Dummy weather poll interval |
| `ORDERBOOK_MOCK_INTERVAL_SEC` | Mock order-book update interval |
| `USE_MOCK_EXCHANGE` | `false` for live Kalshi WebSocket |
| `USE_MOCK_WEATHER` | `false` for Open-Meteo |
| `KALSHI_API_KEY_ID` / `KALSHI_PRIVATE_KEY_PATH` | Kalshi credentials |
| `KALSHI_USE_DEMO` | `true` = demo API hosts (recommended first) |
| `LOG_LEVEL` | Python logging level |

## Connecting APIs

See step-by-step setup in the response docs below, or run:

```bash
cp .env.example .env
# edit .env with your Kalshi key + ticker
pip install pydantic pydantic-settings scipy websockets cryptography httpx pytest
export PYTHONPATH=src
python scripts/test_connections.py
```

Phased rollout: (1) weather only, (2) Kalshi demo read-only, (3) production.

## Extending

1. Subclass `BaseStrategy` and implement `evaluate_imbalance`.
2. Register the strategy in `main.py` (or a factory module).
3. Use `OpenMeteoFeeder` or add another feed under `feeds/`.
4. Use `KalshiOrderBookWebSocket` with `USE_MOCK_EXCHANGE=false`.

## Tests

```bash
pytest
```
