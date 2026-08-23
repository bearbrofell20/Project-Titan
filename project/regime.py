"""Market-regime classifier — objective, causal.

Per bar, using only past data:
  * trend strength : Wilder ADX
  * direction      : sign of EMA(50) slope over `slope_lag` bars
  * volatility     : ATR vs its own rolling median (expansion / contraction)

Regime labels: "trend_up", "trend_down", "range", plus a boolean "expansion".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from data_manager import Bar
import indicators as ind


@dataclass
class RegimeParams:
    adx_period: int = 14
    trend_adx: float = 25.0
    range_adx: float = 18.0
    ema_period: int = 50
    slope_lag: int = 10
    atr_period: int = 14
    vol_window: int = 100
    vol_mult: float = 1.3


@dataclass
class Regime:
    label: List[str]           # "trend_up" / "trend_down" / "range" / "neutral"
    expansion: List[bool]
    adx: List[Optional[float]]
    atr: List[Optional[float]]


def classify(bars: List[Bar], p: RegimeParams = RegimeParams()) -> Regime:
    highs = [b.h for b in bars]; lows = [b.l for b in bars]; closes = [b.c for b in bars]
    adx = ind.adx(highs, lows, closes, p.adx_period)
    atr = ind.atr(highs, lows, closes, p.atr_period)
    ema = ind.ema(closes, p.ema_period)
    n = len(bars)
    label = ["neutral"] * n
    expansion = [False] * n
    for i in range(n):
        a = adx[i]
        if a is None or ema[i] is None or i < p.slope_lag or ema[i - p.slope_lag] is None:
            continue
        slope = ema[i] - ema[i - p.slope_lag]
        if a >= p.trend_adx:
            label[i] = "trend_up" if slope > 0 else "trend_down"
        elif a < p.range_adx:
            label[i] = "range"
        # volatility expansion vs rolling median ATR
        if i >= p.vol_window and atr[i]:
            window = [x for x in atr[i - p.vol_window:i] if x]
            if window:
                med = sorted(window)[len(window) // 2]
                expansion[i] = atr[i] > p.vol_mult * med
    return Regime(label=label, expansion=expansion, adx=adx, atr=atr)
