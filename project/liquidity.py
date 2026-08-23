"""Liquidity engine — objective levels and sweep detection, no-look-ahead.

Levels a bar can reference using only the PAST:
  * previous UTC day high / low
  * previous session high / low (Asian/London/NY by UTC hour)
Sweep (objective): the bar's wick pierces a level but the bar CLOSES back on the
original side — stops beyond the level were taken and price rejected.
  * bullish sweep = swept a LOW (sell-side liquidity grabbed) -> potential up
  * bearish sweep = swept a HIGH (buy-side liquidity grabbed) -> potential down
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import List, Optional

from data_manager import Bar

SESSIONS = {"asian": (0, 7), "london": (7, 12), "ny": (12, 21)}


@dataclass
class Levels:
    prev_day_high: List[Optional[float]]
    prev_day_low: List[Optional[float]]


def prev_day_levels(bars: List[Bar]) -> Levels:
    """For each bar, the high/low of the previous UTC calendar day (causal)."""
    day_hi: dict = {}
    day_lo: dict = {}
    for b in bars:
        d = dt.datetime.utcfromtimestamp(b.ts).toordinal()
        day_hi[d] = max(day_hi.get(d, b.h), b.h)
        day_lo[d] = min(day_lo.get(d, b.l), b.l)
    pdh, pdl = [], []
    # NOTE: using the *completed* previous day only. Within day D we know all of D-1.
    for b in bars:
        d = dt.datetime.utcfromtimestamp(b.ts).toordinal()
        pdh.append(day_hi.get(d - 1))
        pdl.append(day_lo.get(d - 1))
    return Levels(pdh, pdl)


def sweeps(bars: List[Bar], levels: Levels, tol_frac: float = 0.0):
    """Return per-bar sweep direction: +1 bullish (swept prev-day low & closed
    back above), -1 bearish (swept prev-day high & closed back below), else 0."""
    out = [0] * len(bars)
    for i, b in enumerate(bars):
        pdh, pdl = levels.prev_day_high[i], levels.prev_day_low[i]
        if pdl is not None and b.l < pdl and b.c > pdl:
            out[i] = 1
        elif pdh is not None and b.h > pdh and b.c < pdh:
            out[i] = -1
    return out
