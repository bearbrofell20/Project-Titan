"""Objective entry-signal generators for the core strategy families.

Each returns a per-bar direction array (+1/-1/0) decided at bar i's close,
executed next bar by the backtester. Pure, causal.
"""

from __future__ import annotations

from typing import List

from data_manager import Bar
import indicators as ind


def trend_cross(bars: List[Bar], fast: int = 20, slow: int = 60) -> List[int]:
    closes = [b.c for b in bars]
    ef, es = ind.ema(closes, fast), ind.ema(closes, slow)
    d = [0] * len(bars)
    for i in range(1, len(bars)):
        if None in (ef[i], ef[i - 1], es[i], es[i - 1]):
            continue
        if ef[i - 1] <= es[i - 1] and ef[i] > es[i]:
            d[i] = 1
        elif ef[i - 1] >= es[i - 1] and ef[i] < es[i]:
            d[i] = -1
    return d


def mean_reversion(bars: List[Bar], ema_period: int = 20, k_atr: float = 1.5,
                   atr_period: int = 14) -> List[int]:
    """Fade extension: close k*ATR below EMA -> long (bet on reversion), above -> short."""
    closes = [b.c for b in bars]
    em = ind.ema(closes, ema_period)
    atr = ind.atr([b.h for b in bars], [b.l for b in bars], closes, atr_period)
    d = [0] * len(bars)
    for i in range(len(bars)):
        if em[i] is None or not atr[i]:
            continue
        dev = closes[i] - em[i]
        if dev <= -k_atr * atr[i]:
            d[i] = 1
        elif dev >= k_atr * atr[i]:
            d[i] = -1
    return d


def breakout(bars: List[Bar], lookback: int = 20) -> List[int]:
    """Donchian breakout: close above prior N-bar high -> long; below prior low -> short."""
    d = [0] * len(bars)
    for i in range(lookback, len(bars)):
        prior_hi = max(b.h for b in bars[i - lookback:i])
        prior_lo = min(b.l for b in bars[i - lookback:i])
        if bars[i].c > prior_hi:
            d[i] = 1
        elif bars[i].c < prior_lo:
            d[i] = -1
    return d


def gate(direction: List[int], keep) -> List[int]:
    """Zero out signals where keep(i) is False (regime gating)."""
    return [d if (d != 0 and keep(i)) else 0 for i, d in enumerate(direction)]
