"""Kalshi REST helpers (portfolio balance, market data, etc.)."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlencode

import httpx

from kalshi_bot.config import Settings
from kalshi_bot.exchange.kalshi_auth import build_auth_headers, load_private_key

logger = logging.getLogger(__name__)

_BALANCE_PATH = "/trade-api/v2/portfolio/balance"


def _api_path(relative: str) -> str:
    """Turn ``/markets`` into the signed path ``/trade-api/v2/markets``."""
    relative = relative if relative.startswith("/") else f"/{relative}"
    if relative.startswith("/trade-api/"):
        return relative
    return f"/trade-api/v2{relative}"


async def kalshi_get_json(
    settings: Settings,
    path: str,
    *,
    params: dict[str, str | int] | None = None,
    timeout: float = 20.0,
) -> dict[str, Any]:
    """
    Authenticated GET against the Kalshi trade API.

    Uses the same authenticated signing as portfolio balance requests.
    """
    if not settings.kalshi_api_key_id or not settings.kalshi_private_key_path:
        raise ValueError("Kalshi API credentials required for REST requests")

    relative = path if path.startswith("/") else f"/{path}"
    signed_path = _api_path(relative)
    query = urlencode(params) if params else ""
    sign_path = f"{signed_path}?{query}" if query else signed_path
    private_key = load_private_key(settings.kalshi_private_key_path)
    headers = build_auth_headers(
        settings.kalshi_api_key_id,
        private_key,
        method="GET",
        path=sign_path,
    )
    url = f"{settings.kalshi_api_base_url.rstrip('/')}{relative}"
    if query:
        url = f"{url}?{query}"

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(url, headers=headers)
        response.raise_for_status()
        payload = response.json()

    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object from {path}, got {type(payload)}")
    return payload


async def kalshi_post_json(
    settings: Settings,
    path: str,
    *,
    json_body: dict[str, Any],
    timeout: float = 20.0,
) -> dict[str, Any]:
    """Authenticated POST against the Kalshi trade API."""
    if not settings.kalshi_api_key_id or not settings.kalshi_private_key_path:
        raise ValueError("Kalshi API credentials required for REST requests")

    relative = path if path.startswith("/") else f"/{path}"
    signed_path = _api_path(relative)
    private_key = load_private_key(settings.kalshi_private_key_path)
    headers = build_auth_headers(
        settings.kalshi_api_key_id,
        private_key,
        method="POST",
        path=signed_path,
    )
    headers["Content-Type"] = "application/json"
    url = f"{settings.kalshi_api_base_url.rstrip('/')}{relative}"

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(url, headers=headers, json=json_body)
        response.raise_for_status()
        payload = response.json()

    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object from POST {path}, got {type(payload)}")
    return payload


async def fetch_account_balance_dollars(settings: Settings) -> float:
    """
    Return available account balance in dollars.

    In mock exchange mode, uses ``mock_account_balance_dollars`` (default $11).
    """
    if settings.use_mock_exchange:
        if settings.mock_account_balance_dollars is not None:
            return settings.mock_account_balance_dollars
        return 0.0

    if not settings.kalshi_api_key_id or not settings.kalshi_private_key_path:
        raise ValueError("Kalshi API credentials required to fetch account balance")

    private_key = load_private_key(settings.kalshi_private_key_path)
    headers = build_auth_headers(
        settings.kalshi_api_key_id,
        private_key,
        method="GET",
        path=_BALANCE_PATH,
    )
    url = f"{settings.kalshi_api_base_url.rstrip('/')}/portfolio/balance"

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(url, headers=headers)
        response.raise_for_status()
        payload = response.json()

    balance_cents = _extract_balance_cents(payload)
    dollars = balance_cents / 100.0
    logger.debug("kalshi account balance=%.2f", dollars)
    return dollars


def _extract_balance_cents(payload: dict) -> int:
    if "balance" in payload:
        return int(payload["balance"])
    if "portfolio_balance" in payload:
        return int(payload["portfolio_balance"])
    nested = payload.get("portfolio") or payload.get("data") or {}
    if isinstance(nested, dict):
        for key in ("balance", "portfolio_balance", "available_balance"):
            if key in nested:
                return int(nested[key])
    raise ValueError(f"Could not parse balance from response: {payload!r}")
