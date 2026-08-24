"""Data loading, validation, and higher-timeframe resampling.

Candle schema (matches the cached OANDA bid/mid/ask format used repo-wide):
    {"time": <epoch seconds, UTC, bar OPEN>, "complete": bool,
     "bid": {o,h,l,c}, "mid": {o,h,l,c}, "ask": {o,h,l,c}}

All timestamps are UTC epoch seconds. Only completed candles are used. H4 candles
are built from M15 so the regime filter shares one real bid/ask source, and each
H4 candle carries an explicit `end_ts` — the instant it is first fully known — so
the backtester can enforce "no future HTF leakage".
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

log = logging.getLogger("data")

M15_SEC = 15 * 60
TF_SECONDS = {"M5": 300, "M15": 900, "H1": 3600, "H4": 4 * 3600}


@dataclass
class Bar:
    ts: int                 # OPEN time, UTC epoch
    o: float; h: float; l: float; c: float          # mid OHLC
    bid_c: float; ask_c: float                       # close bid/ask (for fills)
    end_ts: int             # instant this bar is fully known (open + tf duration)

    @property
    def hour_utc(self) -> int:
        return dt.datetime.utcfromtimestamp(self.ts).hour

    @property
    def dow(self) -> int:
        return dt.datetime.utcfromtimestamp(self.ts).weekday()


def _mid(c: dict, k: str) -> float:
    return float(c["mid"][k])


def load_candles(path: str) -> List[dict]:
    raw = json.loads(Path(path).read_text())
    return [c for c in raw if c.get("complete", True)]


def validate(candles: List[dict], tf_sec: int) -> Dict[str, int]:
    """Report data-quality issues; never silently fabricate. Returns a report."""
    seen = set()
    dupes = gaps = malformed = 0
    prev_ts: Optional[int] = None
    for c in candles:
        t = int(c["time"])
        if t in seen:
            dupes += 1
        seen.add(t)
        m = c.get("mid", {})
        try:
            o, h, l, cl = m["o"], m["h"], m["l"], m["c"]
            if not (h >= max(o, cl) and l <= min(o, cl) and h >= l):
                malformed += 1
        except Exception:
            malformed += 1
        if prev_ts is not None:
            step = t - prev_ts
            if step > tf_sec:            # a hole (weekends excluded below)
                # ignore the normal Fri->Sun weekend gap (~48-64h)
                if not (step >= 47 * 3600 and step <= 66 * 3600):
                    gaps += 1
        prev_ts = t
    return {"bars": len(candles), "duplicates": dupes,
            "gaps": gaps, "malformed": malformed}


def to_bars(candles: List[dict], tf: str) -> List[Bar]:
    dur = TF_SECONDS[tf]
    out = []
    for c in candles:
        t = int(c["time"])
        out.append(Bar(ts=t, o=_mid(c, "o"), h=_mid(c, "h"), l=_mid(c, "l"),
                       c=_mid(c, "c"), bid_c=float(c["bid"]["c"]),
                       ask_c=float(c["ask"]["c"]), end_ts=t + dur))
    return out


def resample_h4(m15: List[Bar]) -> List[Bar]:
    """Aggregate M15 bars into H4 buckets aligned to 00:00 UTC.

    An H4 bar's `end_ts` is its bucket start + 4h — the moment it completes and
    becomes usable. We only emit a bucket once at least one M15 bar lands in it;
    partial final buckets are still emitted but their end_ts guards usage.
    """
    if not m15:
        return []
    buckets: Dict[int, List[Bar]] = {}
    for b in m15:
        start = b.ts - (b.ts % (4 * 3600))
        buckets.setdefault(start, []).append(b)
    out = []
    for start in sorted(buckets):
        grp = buckets[start]
        out.append(Bar(
            ts=start, o=grp[0].o, h=max(x.h for x in grp), l=min(x.l for x in grp),
            c=grp[-1].c, bid_c=grp[-1].bid_c, ask_c=grp[-1].ask_c,
            end_ts=start + 4 * 3600))
    return out


def utc(ts: int) -> str:
    return dt.datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
