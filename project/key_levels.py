"""Key-level engine + level-reaction strategy — objective, causal.

Levels a bar can reference using only completed history:
  * previous completed SESSION high/low (Asian/London/NY by UTC hour)
  * previous completed H1 candle high/low
  * previous completed H4 candle high/low
  * previous day high/low

Reaction trade (the "change in pattern at a level"):
  * price approaches a level and pokes THROUGH it but the bar CLOSES back on the
    original side -> rejection. Fade it, stop beyond the wick, target next level / R.
    - resistance rejection (approached from below, closed back below) -> SHORT
    - support rejection   (approached from above, closed back above) -> LONG
"""

from __future__ import annotations

import datetime as dt
from typing import Dict, List, Optional

from data_manager import Bar
from strategy import Signals
import indicators as ind

SESS = [("asian", 0, 7), ("london", 7, 12), ("ny", 12, 21)]


def _sess_name(hour: int) -> Optional[str]:
    for name, lo, hi in SESS:
        if lo <= hour < hi:
            return name
    return None


def prev_session_levels(bars: List[Bar]):
    """Per-bar (prev_session_high, prev_session_low) = the last COMPLETED session."""
    cur_name = None
    cur_hi = cur_lo = None
    last_hi = last_lo = None
    ph, pl = [None] * len(bars), [None] * len(bars)
    for i, b in enumerate(bars):
        name = _sess_name(dt.datetime.utcfromtimestamp(b.ts).hour)
        if name != cur_name:
            if cur_hi is not None:      # a session just completed
                last_hi, last_lo = cur_hi, cur_lo
            cur_name, cur_hi, cur_lo = name, b.h, b.l
        else:
            cur_hi = max(cur_hi, b.h) if cur_hi is not None else b.h
            cur_lo = min(cur_lo, b.l) if cur_lo is not None else b.l
        ph[i], pl[i] = last_hi, last_lo
    return ph, pl


def prev_tf_levels(bars: List[Bar], tf_sec: int):
    """Per-bar high/low of the previous COMPLETED bucket of size tf_sec."""
    hi = lo = None
    cur_bucket = None
    cur_hi = cur_lo = None
    outh, outl = [None] * len(bars), [None] * len(bars)
    for i, b in enumerate(bars):
        bucket = b.ts - (b.ts % tf_sec)
        if bucket != cur_bucket:
            if cur_hi is not None:
                hi, lo = cur_hi, cur_lo
            cur_bucket, cur_hi, cur_lo = bucket, b.h, b.l
        else:
            cur_hi, cur_lo = max(cur_hi, b.h), min(cur_lo, b.l)
        outh[i], outl[i] = hi, lo
    return outh, outl


def active_levels(bars: List[Bar]) -> List[List[float]]:
    """Assemble all key levels available to each bar."""
    psh, psl = prev_session_levels(bars)
    h1h, h1l = prev_tf_levels(bars, 3600)
    h4h, h4l = prev_tf_levels(bars, 4 * 3600)
    dayh, dayl = prev_tf_levels(bars, 24 * 3600)
    out = []
    for i in range(len(bars)):
        lv = [x for x in (psh[i], psl[i], h1h[i], h1l[i], h4h[i], h4l[i], dayh[i], dayl[i])
              if x is not None]
        out.append(lv)
    return out


def reaction_signals(bars: List[Bar], tol_atr: float = 0.10, atr_period: int = 14) -> Signals:
    """Fade a rejection wick at the nearest key level; stop beyond the wick."""
    n = len(bars)
    atr = ind.atr([b.h for b in bars], [b.l for b in bars], [b.c for b in bars], atr_period)
    levels = active_levels(bars)
    direction = [0] * n
    stop_px: List = [None] * n
    for i in range(1, n):
        if not atr[i]:
            continue
        tol = tol_atr * atr[i]
        b = bars[i]
        best = None
        for lv in levels[i]:
            # bar must interact with the level (poke through within tolerance)
            if b.l - tol <= lv <= b.h + tol:
                dist = abs(b.c - lv)
                if best is None or dist < best[1]:
                    best = (lv, dist)
        if best is None:
            continue
        lv = best[0]
        # resistance rejection: poked above, closed back below -> short
        if b.h > lv and b.c < lv:
            direction[i] = -1
            stop_px[i] = b.h
        # support rejection: poked below, closed back above -> long
        elif b.l < lv and b.c > lv:
            direction[i] = 1
            stop_px[i] = b.l
    return Signals(direction=direction, atr=atr, ema=[None] * n,
                   h4_ema_at=[None] * n, h4_close_at=[None] * n,
                   stop_px=stop_px, target_px=None)
