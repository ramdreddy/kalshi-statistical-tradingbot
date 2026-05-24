"""Application configuration loaded from environment variables."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings; values come from env vars or a `.env` file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    kalshi_api_base_url: str = "https://api.elections.kalshi.com/trade-api/v2"
    kalshi_ws_url: str = "wss://api.elections.kalshi.com/trade-api/ws/v2"
    kalshi_market_ticker: str = "KXHIGHNY-26MAY24-T75"
    log_level: str = "INFO"
    weather_poll_interval_sec: float = 5.0
    orderbook_mock_interval_sec: float = 1.0
    use_mock_exchange: bool = True


@lru_cache
def get_settings() -> Settings:
    """Return cached settings singleton."""
    return Settings()
