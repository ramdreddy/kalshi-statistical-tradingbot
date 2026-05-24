import pytest

from kalshi_bot.exchange.mock_ws import MockKalshiOrderBookWebSocket


@pytest.mark.asyncio
async def test_mock_ws_stream_yields_snapshots() -> None:
    ws = MockKalshiOrderBookWebSocket(ticker="TEST", interval_sec=0.01, seed=42)
    stream = ws.stream()
    snapshot = await stream.__anext__()
    await stream.aclose()
    assert snapshot.ticker == "TEST"
    assert snapshot.best_bid_cents is not None
    assert snapshot.best_ask_cents is not None
