from kalshi_bot.config import Settings, get_settings


def test_settings_reads_env(monkeypatch) -> None:
    monkeypatch.setenv("KALSHI_MARKET_TICKER", "TEST-TICKER")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    get_settings.cache_clear()
    settings = Settings()
    assert settings.kalshi_market_ticker == "TEST-TICKER"
    assert settings.log_level == "DEBUG"
    get_settings.cache_clear()


def test_settings_defaults(monkeypatch) -> None:
    monkeypatch.delenv("KALSHI_MARKET_TICKER", raising=False)
    monkeypatch.delenv("USE_MOCK_EXCHANGE", raising=False)
    settings = Settings(_env_file=None)
    assert settings.use_mock_exchange is True
    assert settings.kalshi_market_ticker == "KXHIGHNY-26MAY24-T75"
