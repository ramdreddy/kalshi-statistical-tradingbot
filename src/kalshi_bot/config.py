"""Application configuration loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache
from typing import Optional

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEMO_API = "https://external-api.demo.kalshi.co/trade-api/v2"
_DEMO_WS = "wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2"
_PROD_API = "https://external-api.kalshi.com/trade-api/v2"
_PROD_WS = "wss://external-api-ws.kalshi.com/trade-api/ws/v2"


class Settings(BaseSettings):
    """Runtime settings; values come from env vars or a `.env` file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Kalshi
    kalshi_use_demo: bool = True
    kalshi_api_base_url: str = _DEMO_API
    kalshi_ws_url: str = _DEMO_WS
    kalshi_api_key_id: str = ""
    kalshi_private_key_path: str = ""
    kalshi_market_ticker: str = "KXHIGHNY-26MAY24-T75"
    auto_discover_markets: bool = True
    # single = one series (WEATHER_SERIES_TICKER); all = every Kalshi weather series
    weather_discovery_scope: str = "all"
    weather_series_ticker: str = "KXHIGHNY"
    # Optional comma-separated override when scope=all, e.g. KXHIGHNY,KXHIGHCHI
    weather_series_tickers: str = ""
    weather_event_ticker: str = ""
    # Caps for scope=all (WebSocket cannot handle hundreds of tickers at once)
    weather_max_series: int = 20
    weather_max_markets: int = 60
    weather_ws_subscribe_batch_size: int = 20

    # Order execution (requires live Kalshi + API key with trading permission)
    trading_enabled: bool = False
    order_cooldown_sec: float = 600.0
    order_price_slippage_cents: int = 1
    max_orders_per_session: int = 10
    # first_signal = trade immediately on each book update (legacy)
    # best_edge = scan all books, place up to max_orders on highest edge_cents
    order_selection_mode: str = "best_edge"
    order_batch_debounce_sec: float = 2.0
    balance_cache_sec: float = 60.0
    signal_log_cooldown_sec: float = 60.0

    # Weather (mock | open_meteo | nws)
    use_mock_weather: bool = False
    weather_provider: str = "nws"
    weather_location: str = "New York, NY (Central Park)"
    weather_latitude: float = 40.7812
    weather_longitude: float = -73.9665
    nws_user_agent: str = "kalshi-weather-bot/0.1.0 (contact@example.com)"
    weather_strike_temp_f: float = 75.0
    weather_forecast_std_f: float = 3.5

    # Risk / sizing
    bet_size_dollars: float = 1.0
    max_contracts_per_order: int = 10
    min_account_balance_dollars: float = 3.0
    mock_account_balance_dollars: Optional[float] = 11.0

    # Runtime
    log_level: str = "INFO"
    weather_poll_interval_sec: float = 300.0
    orderbook_mock_interval_sec: float = 1.0
    use_mock_exchange: bool = True

    @model_validator(mode="after")
    def apply_environment_defaults(self) -> "Settings":
        self.kalshi_api_key_id = self.kalshi_api_key_id.strip()
        self.kalshi_private_key_path = self.kalshi_private_key_path.strip()
        if self.kalshi_use_demo:
            self.kalshi_api_base_url = _DEMO_API
            self.kalshi_ws_url = _DEMO_WS
        else:
            self.kalshi_api_base_url = _PROD_API
            self.kalshi_ws_url = _PROD_WS
        return self


@lru_cache
def get_settings() -> Settings:
    """Return cached settings singleton."""
    return Settings()
