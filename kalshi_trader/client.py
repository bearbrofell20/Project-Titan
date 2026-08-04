"""Authenticated REST client for the Kalshi trading API.

Kalshi's current API authenticates each request with an RSA key pair.  For every
call you sign the string ``{timestamp_ms}{METHOD}{path}`` with RSA-PSS/SHA-256
and send three headers:

* ``KALSHI-ACCESS-KEY``       — your API key id
* ``KALSHI-ACCESS-TIMESTAMP`` — milliseconds since epoch (also part of the signature)
* ``KALSHI-ACCESS-SIGNATURE`` — base64 of the signature

The heavy dependencies (``requests`` and ``cryptography``) are imported lazily so
that the rest of the package — models, strategies, risk, and their tests — can be
used without them installed.
"""

from __future__ import annotations

import base64
import json
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit

from .config import Config
from .models import Market, OrderIntent, Position


class KalshiError(RuntimeError):
    """Raised when the Kalshi API returns an error response."""


class KalshiClient:
    """Thin wrapper over the Kalshi REST API with request signing."""

    def __init__(self, config: Config):
        self.config = config
        self._private_key = None  # loaded lazily
        self._session = None      # requests.Session, loaded lazily

    # -- lazy heavy imports ------------------------------------------------
    @property
    def session(self):
        if self._session is None:
            import requests  # noqa: PLC0415 (intentional lazy import)

            self._session = requests.Session()
        return self._session

    def _load_private_key(self):
        if self._private_key is not None:
            return self._private_key
        self.config.require_credentials()
        from cryptography.hazmat.primitives import serialization  # noqa: PLC0415

        with open(self.config.private_key_path, "rb") as fh:
            self._private_key = serialization.load_pem_private_key(
                fh.read(), password=None
            )
        return self._private_key

    # -- signing -----------------------------------------------------------
    def _sign(self, timestamp_ms: str, method: str, path: str) -> str:
        """Return the base64 RSA-PSS signature for one request.

        ``path`` must be the request path *without* the query string, e.g.
        ``/trade-api/v2/portfolio/balance``.
        """
        from cryptography.hazmat.primitives import hashes  # noqa: PLC0415
        from cryptography.hazmat.primitives.asymmetric import padding  # noqa: PLC0415

        key = self._load_private_key()
        message = f"{timestamp_ms}{method}{path}".encode("utf-8")
        signature = key.sign(
            message,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH,
            ),
            hashes.SHA256(),
        )
        return base64.b64encode(signature).decode("utf-8")

    def _headers(self, method: str, url: str) -> Dict[str, str]:
        timestamp_ms = str(int(time.time() * 1000))
        path = urlsplit(url).path  # signature excludes host and query string
        return {
            "KALSHI-ACCESS-KEY": self.config.api_key_id or "",
            "KALSHI-ACCESS-TIMESTAMP": timestamp_ms,
            "KALSHI-ACCESS-SIGNATURE": self._sign(timestamp_ms, method, path),
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    # -- core request ------------------------------------------------------
    def _request(
        self,
        method: str,
        endpoint: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        body: Optional[Dict[str, Any]] = None,
        authenticated: bool = True,
    ) -> Dict[str, Any]:
        url = f"{self.config.base_url}{endpoint}"
        headers = self._headers(method, url) if authenticated else {
            "Accept": "application/json"
        }
        data = json.dumps(body) if body is not None else None
        resp = self.session.request(
            method, url, params=params, data=data, headers=headers, timeout=30
        )
        if resp.status_code >= 400:
            raise KalshiError(
                f"{method} {endpoint} -> {resp.status_code}: {resp.text}"
            )
        if not resp.content:
            return {}
        return resp.json()

    # -- market data (public) ---------------------------------------------
    def get_markets(
        self,
        *,
        limit: int = 100,
        status: str = "open",
        series_ticker: Optional[str] = None,
        event_ticker: Optional[str] = None,
    ) -> List[Market]:
        """Fetch a page of markets."""
        params: Dict[str, Any] = {"limit": limit, "status": status}
        if series_ticker:
            params["series_ticker"] = series_ticker
        if event_ticker:
            params["event_ticker"] = event_ticker
        data = self._request("GET", "/markets", params=params, authenticated=False)
        return [Market.from_api(m) for m in data.get("markets", [])]

    def get_market(self, ticker: str) -> Market:
        data = self._request(
            "GET", f"/markets/{ticker}", authenticated=False
        )
        return Market.from_api(data["market"])

    # -- portfolio (authenticated) ----------------------------------------
    def get_balance_cents(self) -> int:
        """Return the account's available balance in cents."""
        data = self._request("GET", "/portfolio/balance")
        return int(data.get("balance", 0))

    def get_positions(self) -> List[Position]:
        """Return current market positions."""
        data = self._request("GET", "/portfolio/positions")
        positions: List[Position] = []
        for p in data.get("market_positions", []):
            qty = int(p.get("position", 0))
            if qty == 0:
                continue
            positions.append(
                Position(
                    ticker=p["ticker"],
                    quantity=qty,
                    # market_exposure is total cost basis in cents
                    avg_price_cents=int(
                        abs(p.get("market_exposure", 0)) // max(abs(qty), 1)
                    ),
                )
            )
        return positions

    def place_order(self, intent: OrderIntent, client_order_id: str) -> Dict[str, Any]:
        """Submit an order to Kalshi and return the raw order response."""
        payload = intent.to_api_payload(client_order_id)
        return self._request("POST", "/portfolio/orders", body=payload)
