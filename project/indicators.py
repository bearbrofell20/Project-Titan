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


def adx(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float],
        period: int = 14) -> List[Optional[float]]:
    """Wilder's ADX (trend strength). out[i] uses bars 0..i only."""
    n = len(closes)
    out: List[Optional[float]] = [None] * n
    if n < 2 * period:
        return out
    plus_dm, minus_dm, trs = [], [], []
    for i in range(1, n):
        up = highs[i] - highs[i - 1]
        dn = lows[i - 1] - lows[i]
        plus_dm.append(up if (up > dn and up > 0) else 0.0)
        minus_dm.append(dn if (dn > up and dn > 0) else 0.0)
        trs.append(true_range(highs[i], lows[i], closes[i - 1]))
    # Wilder-smoothed +DI/-DI, then DX, then ADX
    def wilder(seq):
        sm = [None] * len(seq)
        s = sum(seq[:period])
        sm[period - 1] = s
        for i in range(period, len(seq)):
            s = s - s / period + seq[i]
            sm[i] = s
        return sm
    sp, sm, st = wilder(plus_dm), wilder(minus_dm), wilder(trs)
    dx = [None] * len(trs)
    for i in range(len(trs)):
        if sp[i] is None or not st[i]:
            continue
        pdi = 100 * sp[i] / st[i]
        mdi = 100 * sm[i] / st[i]
        denom = pdi + mdi
        dx[i] = 100 * abs(pdi - mdi) / denom if denom else 0.0
    # ADX = Wilder average of DX; align back to bar index (offset by 1 for the diff)
    first = period - 1
    vals = [d for d in dx[first:first + period] if d is not None]
    if len(vals) < period:
        return out
    a = sum(vals) / period
    out[first + period] = a
    for i in range(first + period + 1, len(dx)):
        if dx[i] is None:
            continue
        a = (a * (period - 1) + dx[i]) / period
        out[i + 1] = a
    return out


def crossed_up(prev_price: float, prev_ref: float, price: float, ref: float) -> bool:
    """True when price crosses from <= ref to > ref between the two bars."""
    return prev_price <= prev_ref and price > ref


def crossed_down(prev_price: float, prev_ref: float, price: float, ref: float) -> bool:
    return prev_price >= prev_ref and price < ref
