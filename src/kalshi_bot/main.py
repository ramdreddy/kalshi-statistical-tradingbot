"""Application entrypoint: asyncio event loop and market data subscriptions."""

from __future__ import annotations

import asyncio
import logging
import signal

from kalshi_bot.config import Settings, get_settings
from kalshi_bot.engine.bus import EventBus
from kalshi_bot.engine.runner import TradingEngine
from kalshi_bot.exchange.market_discovery import resolve_trading_markets
from kalshi_bot.exchange.mock_ws import MockKalshiOrderBookWebSocket
from kalshi_bot.domain.market import WeatherBracketMarket
from kalshi_bot.feeds.multi_nws import MultiSeriesNWSFeeder
from kalshi_bot.feeds.weather import WeatherFeeder
from kalshi_bot.feeds.nws import NWSFeeder
from kalshi_bot.feeds.open_meteo import OpenMeteoFeeder
from kalshi_bot.feeds.event_dates import event_dates_by_series
from kalshi_bot.feeds.weather_locations import location_for_series, timezone_for_series
from kalshi_bot.strategies.weather_imbalance import WeatherImbalanceStrategy


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-8s [%(name)s] %(message)s",
    )


def _build_weather_feeder(
    settings: Settings,
    markets: list[WeatherBracketMarket],
) -> WeatherFeeder:
    if settings.use_mock_weather:
        return WeatherFeeder(
            location=settings.weather_location,
            poll_interval_sec=settings.weather_poll_interval_sec,
        )

    series_set = {m.series_ticker.upper() for m in markets if m.series_ticker}
    settlement_dates = event_dates_by_series(markets)

    if settings.weather_provider == "nws" and len(series_set) > 1:
        return MultiSeriesNWSFeeder.for_markets(markets, settings)

    if settings.weather_provider == "nws":
        series = next(iter(series_set), settings.weather_series_ticker.upper())
        forecast_date = settlement_dates.get(series)
        if forecast_date is None and markets:
            forecast_date = settlement_dates.get(next(iter(settlement_dates)))
        loc = location_for_series(series)
        if loc is not None:
            return NWSFeeder(
                latitude=loc.latitude,
                longitude=loc.longitude,
                location=loc.label,
                poll_interval_sec=settings.weather_poll_interval_sec,
                user_agent=settings.nws_user_agent,
                series_ticker=series,
                forecast_date=forecast_date,
                timezone=timezone_for_series(series),
            )
        return NWSFeeder(
            latitude=settings.weather_latitude,
            longitude=settings.weather_longitude,
            location=settings.weather_location,
            poll_interval_sec=settings.weather_poll_interval_sec,
            user_agent=settings.nws_user_agent,
            series_ticker=series,
            forecast_date=forecast_date,
            timezone=timezone_for_series(series),
        )
    if settings.weather_provider == "open_meteo":
        return OpenMeteoFeeder(
            latitude=settings.weather_latitude,
            longitude=settings.weather_longitude,
            location=settings.weather_location,
            poll_interval_sec=settings.weather_poll_interval_sec,
        )
    raise ValueError(f"Unknown WEATHER_PROVIDER: {settings.weather_provider}")


def _build_orderbook_ws(settings: Settings, markets: list[WeatherBracketMarket]):
    tickers = [m.ticker for m in markets]
    if settings.use_mock_exchange:
        return MockKalshiOrderBookWebSocket(
            ticker=tickers,
            interval_sec=settings.orderbook_mock_interval_sec,
        )

    if not settings.kalshi_api_key_id or not settings.kalshi_private_key_path:
        raise ValueError(
            "Live Kalshi requires KALSHI_API_KEY_ID and KALSHI_PRIVATE_KEY_PATH in .env"
        )

    from kalshi_bot.exchange.live_ws import KalshiOrderBookWebSocket

    return KalshiOrderBookWebSocket(
        ws_url=settings.kalshi_ws_url,
        api_key_id=settings.kalshi_api_key_id,
        private_key_path=settings.kalshi_private_key_path,
        tickers=tickers,
        subscribe_batch_size=settings.weather_ws_subscribe_batch_size,
    )


async def run_bot() -> None:
    settings = get_settings()
    _configure_logging(settings.log_level)

    logger = logging.getLogger(__name__)
    markets = await resolve_trading_markets(settings)
    tickers = [m.ticker for m in markets]

    logger.info(
        "starting bot markets=%d scope=%s series=%d auto_discover=%s "
        "mock_exchange=%s weather=%s demo=%s trading_enabled=%s "
        "order_selection=%s",
        len(markets),
        settings.weather_discovery_scope,
        len({m.series_ticker for m in markets}),
        settings.auto_discover_markets,
        settings.use_mock_exchange,
        "mock" if settings.use_mock_weather else settings.weather_provider,
        settings.kalshi_use_demo,
        settings.trading_enabled,
        settings.order_selection_mode,
    )
    if settings.trading_enabled and settings.use_mock_exchange:
        logger.warning("TRADING_ENABLED=true with USE_MOCK_EXCHANGE=true — orders will be logged only")
    if settings.trading_enabled and not settings.use_mock_exchange:
        logger.warning(
            "LIVE TRADING ENABLED — bot will place real limit orders up to $%.2f each",
            settings.bet_size_dollars,
        )
    for market in markets:
        logger.info(
            "market ticker=%s event=%s bracket=%s",
            market.ticker,
            market.event_ticker,
            market.describe_bracket(),
        )

    bus = EventBus()
    strategy = WeatherImbalanceStrategy.from_markets(
        markets,
        forecast_std_f=settings.weather_forecast_std_f,
    )
    weather_feeder = _build_weather_feeder(settings, markets)
    orderbook_ws = _build_orderbook_ws(settings, markets)

    engine = TradingEngine(
        bus=bus,
        strategy=strategy,
        weather_feeder=weather_feeder,
        orderbook_ws=orderbook_ws,
        settings=settings,
    )

    if isinstance(weather_feeder, MultiSeriesNWSFeeder):
        logger.info("warming up NWS forecasts for %d cities...", len(weather_feeder.series_tickers))
        engine.seed_weather(await weather_feeder.warm_up())
    elif isinstance(weather_feeder, NWSFeeder):
        austin_weather = await weather_feeder.fetch_metrics()
        engine.seed_weather([austin_weather])
        logger.info(
            "weather ready for %s forecast_high=%.1f°F — evaluating order books",
            austin_weather.series_ticker or settings.weather_series_ticker,
            austin_weather.forecast_high_f or austin_weather.temperature_f,
        )
    elif isinstance(weather_feeder, WeatherFeeder):
        engine.seed_weather([await weather_feeder.fetch_metrics()])

    logger.info(
        "bot running — listening for order books (next NWS poll in %.0fs)",
        settings.weather_poll_interval_sec,
    )

    loop = asyncio.get_running_loop()
    stop = asyncio.Event()

    def _request_shutdown() -> None:
        logger.info("shutdown requested")
        stop.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _request_shutdown)

    run_task = asyncio.create_task(engine.run(), name="trading-engine")
    await stop.wait()
    run_task.cancel()
    try:
        await run_task
    except asyncio.CancelledError:
        logger.info("bot stopped")


def main() -> None:
    asyncio.run(run_bot())


if __name__ == "__main__":
    main()
