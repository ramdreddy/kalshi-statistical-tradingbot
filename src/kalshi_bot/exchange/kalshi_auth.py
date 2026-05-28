"""Kalshi REST/WebSocket request signing (RSA-PSS)."""

from __future__ import annotations

import base64
import time
from pathlib import Path
from urllib.parse import urlparse

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding


def load_private_key(path: str | Path):
    key_path = Path(path).expanduser()
    with key_path.open("rb") as key_file:
        return serialization.load_pem_private_key(key_file.read(), password=None)


def sign_pss_text(private_key, message: str) -> str:
    signature = private_key.sign(
        message.encode("utf-8"),
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.DIGEST_LENGTH,
        ),
        hashes.SHA256(),
    )
    return base64.b64encode(signature).decode("utf-8")


def ws_path_from_url(ws_url: str) -> str:
    """Return the path used when signing a WebSocket handshake."""
    parsed = urlparse(ws_url)
    return parsed.path or "/trade-api/ws/v2"


def build_auth_headers(
    api_key_id: str,
    private_key,
    *,
    method: str = "GET",
    path: str = "/trade-api/ws/v2",
) -> dict[str, str]:
    timestamp = str(int(time.time() * 1000))
    path_only = path.split("?")[0]
    message = f"{timestamp}{method}{path_only}"
    signature = sign_pss_text(private_key, message)
    return {
        "KALSHI-ACCESS-KEY": api_key_id,
        "KALSHI-ACCESS-SIGNATURE": signature,
        "KALSHI-ACCESS-TIMESTAMP": timestamp,
    }
