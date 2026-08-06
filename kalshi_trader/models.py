"""Typed data structures used throughout the trader.

Kalshi contracts are priced in **cents** on a 1–99 scale: a "Yes" price of 60
means the market implies a 60% probability and a filled contract pays out 100
cents if the event resolves Yes.  We keep everything in integer cents to avoid
floating-point money bugs.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class Side(str, Enum):
    """Which contract you are trading."""

    YES = "yes"
    NO = "no"


class Action(str, Enum):
    """Whether you are opening or closing exposure."""

    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    LIMIT = "limit"
    MARKET = "market"


@dataclass(frozen=True)
class Market:
    """A single tradable Kalshi market (one Yes/No question)."""

    ticker: str
    title: str
    status: str                     # e.g. "active", "closed", "settled"
    yes_bid: Optional[int]          # best bid to buy Yes, in cents
    yes_ask: Optional[int]          # best ask to sell you Yes, in cents
    no_bid: Optional[int]
    no_ask: Optional[int]
    last_price: Optional[int]       # last traded Yes price, in cents
    volume: int = 0
    strike: Optional[float] = None  # numeric strike (e.g. BTC "price to beat")
    close_time: Optional[str] = None  # ISO-8601 settlement time

    @property
    def is_tradable(self) -> bool:
        return self.status == "active"

    @property
    def yes_mid(self) -> Optional[float]:
        """Mid price of the Yes contract in cents, or None if no two-sided market."""
        if self.yes_bid is None or self.yes_ask is None:
            return None
        return (self.yes_bid + self.yes_ask) / 2.0

    @classmethod
    def from_api(cls, data: dict) -> "Market":
        """Build a :class:`Market` from a raw Kalshi ``/markets`` payload entry.

        Supports both the legacy integer-cent fields (``yes_bid``) and the
        current dollar-string schema (``yes_bid_dollars``: "0.4500"), which the
        fast crypto markets use. Dollar prices are converted to cents.
        """
        def cents(field):
            # legacy integer cents first
            v = data.get(field)
            if v is not None:
                return int(v)
            # current schema: "<field>_dollars" as a dollar string
            d = data.get(f"{field}_dollars")
            if d in (None, ""):
                return None
            return round(float(d) * 100)

        strike = data.get("floor_strike")
        if strike is None:
            strike = data.get("cap_strike")
        return cls(
            ticker=data["ticker"],
            title=data.get("title", data["ticker"]),
            status=data.get("status", "unknown"),
            yes_bid=cents("yes_bid"),
            yes_ask=cents("yes_ask"),
            no_bid=cents("no_bid"),
            no_ask=cents("no_ask"),
            last_price=cents("last_price"),
            volume=int(data.get("volume", 0) or 0),
            strike=float(strike) if strike is not None else None,
            close_time=data.get("close_time"),
        )


@dataclass(frozen=True)
class Position:
    """A net position held in one market."""

    ticker: str
    quantity: int          # signed: positive = long Yes, negative = long No
    avg_price_cents: int   # average entry price in cents

    @property
    def exposure_cents(self) -> int:
        """Worst-case capital tied up in this position (contracts settle at 100c)."""
        return abs(self.quantity) * self.avg_price_cents


@dataclass(frozen=True)
class OrderIntent:
    """A strategy's *request* to trade — not yet risk-checked or submitted."""

    ticker: str
    action: Action
    side: Side
    quantity: int
    order_type: OrderType = OrderType.LIMIT
    limit_price_cents: Optional[int] = None   # required for LIMIT orders
    reason: str = ""                          # human-readable rationale for logs

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ValueError("quantity must be positive")
        if self.order_type is OrderType.LIMIT:
            if self.limit_price_cents is None:
                raise ValueError("limit orders require limit_price_cents")
            if not 1 <= self.limit_price_cents <= 99:
                raise ValueError("limit_price_cents must be between 1 and 99")

    def to_api_payload(self, client_order_id: str) -> dict:
        """Serialise to the body expected by ``POST /portfolio/orders``."""
        payload = {
            "ticker": self.ticker,
            "client_order_id": client_order_id,
            "action": self.action.value,
            "side": self.side.value,
            "count": self.quantity,
            "type": self.order_type.value,
        }
        if self.order_type is OrderType.LIMIT:
            # Kalshi expects the limit price on the field matching the side.
            price_field = "yes_price" if self.side is Side.YES else "no_price"
            payload[price_field] = self.limit_price_cents
        return payload
