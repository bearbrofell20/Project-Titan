"""Chronological splits and walk-forward (Parts 19-20).

The dataset is split by TIME, never shuffled. The final OOS/holdout slice is
reserved and evaluated once. Walk-forward rolls consecutive train/test windows;
we want positive expectancy in MOST test windows, not one lucky stretch.
"""

from __future__ import annotations

from typing import Callable, Dict, List, Tuple

import metrics
from data_manager import Bar


def split_by_time(m15: List[Bar], fracs=(0.6, 0.2, 0.2)) -> Dict[str, Tuple[int, int]]:
    """Return index ranges for IS / VALIDATION / OOS-holdout by bar index."""
    n = len(m15)
    a = int(n * fracs[0])
    b = int(n * (fracs[0] + fracs[1]))
    return {"IS": (0, a), "VALID": (a, b), "OOS": (b, n)}


def trades_in(trades, lo_ts: int, hi_ts: int):
    return [t for t in trades if lo_ts <= t.entry_ts < hi_ts]


def evaluate_slices(m15: List[Bar], trades) -> Dict[str, Dict]:
    rng = split_by_time(m15)
    out = {}
    for name, (i0, i1) in rng.items():
        lo, hi = m15[i0].ts, (m15[i1].ts if i1 < len(m15) else m15[-1].ts + 1)
        out[name] = metrics.summarize(trades_in(trades, lo, hi))
    return out


def walk_forward(m15: List[Bar], trades, windows: int = 5) -> List[Dict]:
    n = len(m15)
    out = []
    for k in range(windows):
        i0 = int(n * k / windows)
        i1 = int(n * (k + 1) / windows)
        lo, hi = m15[i0].ts, (m15[i1].ts if i1 < n else m15[-1].ts + 1)
        out.append(metrics.summarize(trades_in(trades, lo, hi)))
    return out
