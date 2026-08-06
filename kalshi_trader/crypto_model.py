"""Fair-value model for Kalshi short-duration crypto markets (e.g. KXBTC15M).

Each market asks: will BTC be >= a strike ("price to beat") at a fixed expiry a
few minutes out? Over such a short horizon crypto has no reliable drift, so the
honest fair value is a **driftless binary option**: given the current spot, the
strike, the time left, and recent realized volatility, the probability that spot
finishes at/above the strike is::

    P(S_T >= K) = Phi( (ln(S/K) - 0.5 * sigma^2 * tau) / (sigma * sqrt(tau)) )

The pure functions here are unit-tested; the data fetchers hit free public
endpoints (Coinbase) and are exercised live, not in tests.
"""

from __future__ import annotations

import math
import statistics
from datetime import datetime, timezone

MINUTES_PER_YEAR = 365 * 24 * 60


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def fair_prob_ge(spot: float, strike: float, minutes_left: float, vol_annual: float) -> float:
    """P(spot at expiry >= strike), 0..1, driftless lognormal."""
    if spot <= 0 or strike <= 0:
        return 0.0
    if minutes_left <= 0 or vol_annual <= 0:
        return 1.0 if spot >= strike else 0.0
    tau = minutes_left / MINUTES_PER_YEAR
    sig = vol_annual * math.sqrt(tau)            # stdev of log-return to expiry
    if sig <= 0:
        return 1.0 if spot >= strike else 0.0
    d2 = (math.log(spot / strike) - 0.5 * sig * sig) / sig
    return _norm_cdf(d2)


def fair_value_cents(spot: float, strike: float, minutes_left: float, vol_annual: float) -> float:
    """Fair Yes price in cents (0..100) for a 'BTC >= strike' market."""
    return fair_prob_ge(spot, strike, minutes_left, vol_annual) * 100.0


def minutes_left(close_time_iso: str, now: datetime | None = None) -> float:
    """Minutes from now until an ISO-8601 close time (negative if past)."""
    now = now or datetime.now(timezone.utc)
    close = datetime.fromisoformat(close_time_iso.replace("Z", "+00:00"))
    return (close - now).total_seconds() / 60.0


# --- live data (public endpoints; not unit-tested) -------------------------


def fetch_btc_spot() -> float | None:
    import requests
    try:
        r = requests.get("https://api.coinbase.com/v2/prices/BTC-USD/spot", timeout=8)
        return float(r.json()["data"]["amount"])
    except Exception:
        return None


def fetch_realized_vol_annual(lookback_min: int = 90) -> float | None:
    """Annualized volatility from recent 1-minute BTC closes (Coinbase)."""
    import requests
    try:
        r = requests.get(
            "https://api.exchange.coinbase.com/products/BTC-USD/candles",
            params={"granularity": 60}, timeout=8,
        )
        rows = r.json()  # [[time, low, high, open, close, volume], ...] newest-first
        closes = [float(row[4]) for row in rows[: lookback_min + 1]][::-1]
        rets = [math.log(closes[i] / closes[i - 1])
                for i in range(1, len(closes)) if closes[i - 1] > 0]
        if len(rets) < 5:
            return None
        return statistics.pstdev(rets) * math.sqrt(MINUTES_PER_YEAR)
    except Exception:
        return None
