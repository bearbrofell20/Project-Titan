"""Market-structure engine — objective, no-look-ahead.

Definitions (all measurable, no subjective terms):
  * Swing high at i: bars[i].h is the strict max of highs[i-L .. i+L]. It is only
    CONFIRMED (knowable) at bar i+L. We expose swings with that delay so nothing
    repaints.
  * BOS (break of structure): close beyond the most recent confirmed swing in the
    direction of the prevailing trend (continuation).
  * CHOCH / MSS (change of character / market-structure shift): close beyond the
    most recent confirmed swing AGAINST the prevailing trend (reversal).
  * Displacement: the breaking bar's body / ATR — a measured "strong move".

Everything is computed causally: `events[i]` uses only bars 0..i.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from data_manager import Bar
import indicators as ind


@dataclass
class Swing:
    idx: int          # bar index of the pivot
    price: float
    kind: str         # "high" or "low"
    confirmed_at: int # index at which it became known (idx + L)


@dataclass
class StructureEvent:
    idx: int
    kind: str         # "BOS" or "CHOCH"
    direction: int    # +1 bullish, -1 bearish
    ref_price: float  # the swing level that was broken
    displacement: float  # breaking-bar body / ATR


@dataclass
class StructureState:
    swings: List[Swing] = field(default_factory=list)
    events: List[Optional[StructureEvent]] = field(default_factory=list)
    trend: List[int] = field(default_factory=list)   # per-bar prevailing trend
    last_high: List[Optional[float]] = field(default_factory=list)
    last_low: List[Optional[float]] = field(default_factory=list)


def detect_swings(bars: List[Bar], L: int = 2) -> List[Swing]:
    """Fractal pivots confirmed L bars later (causal)."""
    out = []
    n = len(bars)
    for i in range(L, n - L):
        hi = bars[i].h
        lo = bars[i].l
        if all(hi > bars[j].h for j in range(i - L, i)) and all(hi >= bars[j].h for j in range(i + 1, i + L + 1)):
            out.append(Swing(i, hi, "high", i + L))
        if all(lo < bars[j].l for j in range(i - L, i)) and all(lo <= bars[j].l for j in range(i + 1, i + L + 1)):
            out.append(Swing(i, lo, "low", i + L))
    out.sort(key=lambda s: s.confirmed_at)
    return out


def build_structure(bars: List[Bar], L: int = 2, atr_period: int = 14) -> StructureState:
    """Walk bars causally, maintaining last confirmed swing high/low, prevailing
    trend, and per-bar BOS/CHOCH events. A swing is only usable once confirmed."""
    n = len(bars)
    atr = ind.atr([b.h for b in bars], [b.l for b in bars], [b.c for b in bars], atr_period)
    swings = detect_swings(bars, L)
    # group swing confirmations by the bar at which they become known
    by_conf = {}
    for s in swings:
        by_conf.setdefault(s.confirmed_at, []).append(s)

    st = StructureState(swings=swings, events=[None] * n, trend=[0] * n,
                        last_high=[None] * n, last_low=[None] * n)
    cur_high: Optional[float] = None
    cur_low: Optional[float] = None
    trend = 0
    for i in range(n):
        # 1) ingest swings confirmed exactly at bar i (causal)
        for s in by_conf.get(i, []):
            if s.kind == "high":
                cur_high = s.price
            else:
                cur_low = s.price
        # 2) detect a structure break on this bar's CLOSE
        ev = None
        c = bars[i].c
        body = abs(bars[i].c - bars[i].o)
        disp = (body / atr[i]) if atr[i] else 0.0
        if cur_high is not None and c > cur_high:
            direction = 1
            kind = "BOS" if trend >= 0 else "CHOCH"
            ev = StructureEvent(i, kind, direction, cur_high, disp)
            trend = 1
            cur_high = None  # consumed; wait for the next confirmed swing high
        elif cur_low is not None and c < cur_low:
            direction = -1
            kind = "BOS" if trend <= 0 else "CHOCH"
            ev = StructureEvent(i, kind, direction, cur_low, disp)
            trend = -1
            cur_low = None
        st.events[i] = ev
        st.trend[i] = trend
        st.last_high[i] = cur_high
        st.last_low[i] = cur_low
    return st
