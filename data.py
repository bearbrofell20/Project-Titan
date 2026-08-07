"""Historical market-data layer for defensible backtesting.

Fetches **bid/mid/ask** candles (OANDA ``price=MBA``) so the backtester can
model real fills — buy at the ask, sell at the bid, pay the *actual* per-bar
spread instead of a flat constant — and caches them to disk so validation runs
are reproducible and don't hammer the API.

    from data import load_history
    candles = load_history("EUR_USD", "M5", days=180)   # cached after first pull

Each candle is a dict with ``time`` (epoch int), ``complete``, ``volume`` and
``bid``/``mid``/``ask`` sub-dicts of o/h/l/c floats.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Dict, List, Optional

import oanda_trader as ot
from oanda_trader import candle_epoch

CACHE_DIR = Path(os.getenv("TITAN_DATA_DIR", "market_data"))

# Seconds per bar for the OANDA granularities we use.
_GRAN_SECONDS = {
    "M1": 60, "M5": 300, "M15": 900, "M30": 1800,
    "H1": 3600, "H4": 14400, "D": 86400,
}


def granularity_seconds(g: str) -> int:
    if g not in _GRAN_SECONDS:
        raise ValueError(f"unsupported granularity {g!r}")
    return _GRAN_SECONDS[g]


def _parse(candle: dict) -> dict:
    """Normalize a raw OANDA MBA candle to floats + epoch int."""
    def ohlc(side):
        s = candle[side]
        return {"o": float(s["o"]), "h": float(s["h"]),
                "l": float(s["l"]), "c": float(s["c"])}
    return {
        "time": candle_epoch(candle["time"]),
        "complete": candle.get("complete", True),
        "volume": int(candle.get("volume", 0)),
        "bid": ohlc("bid"), "mid": ohlc("mid"), "ask": ohlc("ask"),
    }


def _cache_path(instrument: str, granularity: str) -> Path:
    return CACHE_DIR / f"{instrument}_{granularity}.json"


def fetch_history(
    client: "ot.OandaClient",
    instrument: str,
    granularity: str = "M5",
    days: int = 180,
    page: int = 5000,
) -> List[dict]:
    """Paginate MBA candles backward until ``days`` of history is covered.

    Returns completed candles oldest -> newest. Weekend gaps are expected in FX,
    so we stop when a page returns nothing new rather than assuming a fixed count.
    """
    want_earliest = time.time() - days * 86400
    out: Dict[int, dict] = {}
    to: Optional[float] = None
    while True:
        params = {"granularity": granularity, "count": page, "price": "MBA"}
        if to is not None:
            params["to"] = f"{to:.3f}"
        raw = client._request("GET", f"/v3/instruments/{instrument}/candles", params=params)
        candles = (raw or {}).get("candles", [])
        if not candles:
            break
        new = 0
        earliest = None
        for c in candles:
            if not c.get("complete", True):
                continue
            p = _parse(c)
            if p["time"] not in out:
                out[p["time"]] = p
                new += 1
            earliest = p["time"] if earliest is None else min(earliest, p["time"])
        if earliest is None or new == 0:
            break
        if earliest <= want_earliest:
            break
        to = earliest  # next page ends just before the current earliest bar
        time.sleep(0.1)  # be polite to the API
    return [out[t] for t in sorted(out)]


def load_history(
    instrument: str,
    granularity: str = "M5",
    days: int = 180,
    refresh: bool = False,
    client: "Optional[ot.OandaClient]" = None,
) -> List[dict]:
    """Load candles from the on-disk cache, fetching + caching on a miss.

    Set ``refresh=True`` to force a re-fetch. Returns oldest -> newest.
    """
    path = _cache_path(instrument, granularity)
    if path.exists() and not refresh:
        cached = json.loads(path.read_text())
        if cached and (cached[-1]["time"] - cached[0]["time"]) >= days * 86400 * 0.9:
            return cached
    client = client or ot.OandaClient(ot._load_api_token())
    candles = fetch_history(client, instrument, granularity, days=days)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(candles))
    return candles


def spread_pips(candle: dict, pip_size: float) -> float:
    """Actual spread (in pips) implied by this bar's bid/ask close."""
    return (candle["ask"]["c"] - candle["bid"]["c"]) / pip_size
