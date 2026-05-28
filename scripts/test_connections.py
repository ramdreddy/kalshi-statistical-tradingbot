#!/usr/bin/env python3
"""Verify Kalshi credentials and weather API before running the bot."""

from __future__ import annotations

import asyncio
import sys

from kalshi_bot.config import get_settings


async def test_weather(settings) -> None:
    from kalshi_bot.exchange.market_discovery import resolve_trading_markets
    from kalshi_bot.main import _build_weather_feeder

    markets = await resolve_trading_markets(settings)
    feeder = _build_weather_feeder(settings, markets)
    metrics = await feeder.fetch_metrics()
    extra = ""
    if metrics.forecast_high_f is not None:
        extra = f" forecast_high={metrics.forecast_high_f:.1f}F"
        if metrics.observed_high_f is not None:
            extra += f" observed_high={metrics.observed_high_f:.1f}F"
    series = f" series={metrics.series_ticker}" if metrics.series_ticker else ""
    print(
        f"[weather] OK source={metrics.source} location={metrics.location}{series} "
        f"temp={metrics.temperature_f:.1f}F{extra}"
    )


def _auth_hint(status_code: int, settings) -> str:
    env = "demo" if settings.kalshi_use_demo else "production"
    other = "production" if settings.kalshi_use_demo else "demo"
    return (
        f"\nKalshi returned HTTP {status_code} (authentication failed).\n"
        f"Current config targets: {env}\n"
        f"  REST: {settings.kalshi_api_base_url}\n"
        f"  WS:   {settings.kalshi_ws_url}\n"
        "Common fixes:\n"
        f"  1. Key created on kalshi.com but KALSHI_USE_DEMO=true → set KALSHI_USE_DEMO=false\n"
        f"  2. Key created on demo.kalshi.co but KALSHI_USE_DEMO=false → set KALSHI_USE_DEMO=true\n"
        "  3. KALSHI_API_KEY_ID must match the .pem file downloaded with that key\n"
        "  4. Re-download key if unsure; old keys cannot be recovered\n"
        "  5. WebSocket 401 with working REST: confirm key has trading/data access; "
        "check system clock is accurate\n"
        f"Try the other environment ({other}) if you are unsure where the key was created."
    )


async def test_kalshi_rest(settings) -> None:
    from kalshi_bot.exchange.kalshi_rest import fetch_account_balance_dollars

    balance = await fetch_account_balance_dollars(settings)
    print(f"[kalshi-rest] OK balance=${balance:.2f}")


async def test_market_discovery(settings) -> None:
    from kalshi_bot.exchange.market_discovery import resolve_trading_markets

    if settings.use_mock_exchange and not settings.auto_discover_markets:
        print("[discovery] skipped (mock exchange, AUTO_DISCOVER_MARKETS=false)")
        return

    markets = await resolve_trading_markets(settings)
    if not markets:
        raise RuntimeError("Market discovery returned no tradeable markets")
    series_count = len({m.series_ticker for m in markets})
    print(
        f"[discovery] OK scope={settings.weather_discovery_scope} "
        f"markets={len(markets)} series={series_count} "
        f"(caps: max_series={settings.weather_max_series} "
        f"max_markets={settings.weather_max_markets})"
    )
    for market in markets[:12]:
        print(f"  - {market.series_ticker} | {market.ticker} ({market.describe_bracket()})")
    if len(markets) > 12:
        print(f"  ... and {len(markets) - 12} more")


async def test_kalshi(settings) -> None:
    from kalshi_bot.exchange.market_discovery import resolve_trading_markets
    from kalshi_bot.exchange.live_ws import KalshiOrderBookWebSocket

    if settings.use_mock_exchange:
        from kalshi_bot.exchange.mock_ws import MockKalshiOrderBookWebSocket

        ws = MockKalshiOrderBookWebSocket(ticker=settings.kalshi_market_ticker, interval_sec=0.1)
        stream = ws.stream()
        book = await stream.__anext__()
        await stream.aclose()
        print(f"[kalshi-mock] OK ticker={book.ticker} bid={book.best_bid_cents} ask={book.best_ask_cents}")
        return

    if not settings.kalshi_api_key_id or not settings.kalshi_private_key_path:
        raise RuntimeError("Set KALSHI_API_KEY_ID and KALSHI_PRIVATE_KEY_PATH in .env")

    print(
        f"[kalshi] using {'demo' if settings.kalshi_use_demo else 'production'} "
        f"key_id={settings.kalshi_api_key_id[:8]}..."
    )

    import httpx

    try:
        await test_kalshi_rest(settings)
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(_auth_hint(exc.response.status_code, settings)) from exc

    markets = await resolve_trading_markets(settings)
    tickers = [m.ticker for m in markets]
    test_count = min(6, len(tickers), settings.weather_ws_subscribe_batch_size)
    sample = tickers[:test_count]
    print(f"[kalshi-live] testing WebSocket with {test_count} ticker(s) (of {len(tickers)} discovered)")

    ws = KalshiOrderBookWebSocket(
        ws_url=settings.kalshi_ws_url,
        api_key_id=settings.kalshi_api_key_id,
        private_key_path=settings.kalshi_private_key_path,
        tickers=sample,
        subscribe_batch_size=settings.weather_ws_subscribe_batch_size,
    )

    try:
        await ws.connect()
    except Exception as exc:
        if "401" in str(exc):
            raise RuntimeError(
                f"WebSocket handshake rejected (401). This is an auth issue, not market count.\n"
                f"{_auth_hint(401, settings)}"
            ) from exc
        raise

    await ws.subscribe_orderbook()
    seen: set[str] = set()
    try:
        for _ in range(60):
            raw = await asyncio.wait_for(ws._ws.recv(), timeout=20.0)
            import json

            data = json.loads(raw)
            msg_type = data.get("type")
            if msg_type == "error":
                code = data.get("msg", {}).get("code")
                msg = data.get("msg", {}).get("msg")
                raise RuntimeError(f"Kalshi WebSocket error {code}: {msg}")
            if msg_type == "orderbook_snapshot":
                from kalshi_bot.exchange.live_ws import snapshot_from_message

                msg = data.get("msg") or {}
                ticker = str(msg.get("market_ticker") or sample[0]).upper()
                book = snapshot_from_message(msg, ticker)
                if book is not None and book.ticker not in seen:
                    seen.add(book.ticker)
                    if book.best_bid_cents is None and book.best_ask_cents is None:
                        print(
                            f"[kalshi-live] OK ticker={book.ticker} "
                            "(empty orderbook — no resting orders right now)"
                        )
                    else:
                        print(
                            f"[kalshi-live] OK ticker={book.ticker} "
                            f"bid={book.best_bid_cents} ask={book.best_ask_cents}"
                        )
                    if len(seen) >= 1:
                        return
            elif msg_type == "subscribed":
                print(f"[kalshi-live] subscribed: {data.get('msg', data)}")
    finally:
        await ws.disconnect()

    raise RuntimeError(
        "Timed out waiting for orderbook snapshot. "
        f"Sample tickers={sample}"
    )


async def main() -> None:
    settings = get_settings()
    weather_mode = "mock" if settings.use_mock_weather else settings.weather_provider
    print(f"mock_exchange={settings.use_mock_exchange} weather={weather_mode}")
    await test_market_discovery(settings)
    await test_weather(settings)
    await test_kalshi(settings)
    print("All connection checks passed.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
