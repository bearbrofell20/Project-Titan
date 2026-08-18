"""Pure, vectorized indicators. No indicator may read a future bar.

Each function returns a list aligned to the input closes/candles, where index i
is computed using only data at indices <= i. Warmup positions are None.
"""

from __future__ import annotations

from typing import List, Optional, Sequence


def ema(values: Sequence[float], period: int) -> List[Optional[float]]:
    """Exponential moving average. out[i] uses values[0..i] only."""
    if period <= 0:
        raise ValueError("period must be positive")
    k = 2.0 / (period + 1.0)
    out: List[Optional[float]] = [None] * len(values)
    e: Optional[float] = None
    for i, v in enumerate(values):
        e = v if e is None else (v - e) * k + e
        # only expose once we have `period` observations, so early noise is hidden
        if i >= period - 1:
            out[i] = e
    return out


def true_range(high: float, low: float, prev_close: Optional[float]) -> float:
    if prev_close is None:
        return high - low
    return max(high - low, abs(high - prev_close), abs(low - prev_close))


def atr(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float],
        period: int) -> List[Optional[float]]:
    """Wilder's ATR. out[i] uses bars 0..i only."""
    n = len(closes)
    out: List[Optional[float]] = [None] * n
    trs: List[float] = []
    a: Optional[float] = None
    for i in range(n):
        pc = closes[i - 1] if i > 0 else None
        tr = true_range(highs[i], lows[i], pc)
        trs.append(tr)
        if i == period - 1:
            a = sum(trs[:period]) / period      # seed = simple mean of first `period` TRs
            out[i] = a
        elif i >= period:
            a = (a * (period - 1) + tr) / period  # Wilder smoothing
            out[i] = a
    return out


def crossed_up(prev_price: float, prev_ref: float, price: float, ref: float) -> bool:
    """True when price crosses from <= ref to > ref between the two bars."""
    return prev_price <= prev_ref and price > ref


def crossed_down(prev_price: float, prev_ref: float, price: float, ref: float) -> bool:
    return prev_price >= prev_ref and price < ref
