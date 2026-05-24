"""Application entrypoint: asyncio event loop and mock Kalshi subscription."""

import asyncio
import logging
import signal

from kalshi_bot.config import get_settings
from kalshi_bot.engine.bus import EventBus
from kalshi_bot.engine.runner import TradingEngine
from kalshi_bot.exchange.mock_ws import MockKalshiOrderBookWebSocket
from kalshi_bot.feeds.weather import WeatherFeeder
from kalshi_bot.strategies.weather_imbalance import WeatherImbalanceStrategy


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-8s [%(name)s] %(message)s",
    )


async def run_bot() -> None:
    settings = get_settings()
    _configure_logging(settings.log_level)

    logger = logging.getLogger(__name__)
    logger.info(
        "starting bot ticker=%s mock_exchange=%s",
        settings.kalshi_market_ticker,
        settings.use_mock_exchange,
    )

    bus = EventBus()
    strategy = WeatherImbalanceStrategy(strike_temp_f=75.0)
    weather_feeder = WeatherFeeder(
        location="New York, NY",
        poll_interval_sec=settings.weather_poll_interval_sec,
    )

    if not settings.use_mock_exchange:
        raise NotImplementedError(
            "Live Kalshi WebSocket integration is not implemented; "
            "set USE_MOCK_EXCHANGE=true"
        )

    orderbook_ws = MockKalshiOrderBookWebSocket(
        ticker=settings.kalshi_market_ticker,
        interval_sec=settings.orderbook_mock_interval_sec,
    )

    engine = TradingEngine(
        bus=bus,
        strategy=strategy,
        weather_feeder=weather_feeder,
        orderbook_ws=orderbook_ws,
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
