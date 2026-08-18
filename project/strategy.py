"""Baseline strategy (Part 5), implemented with strict no-look-ahead.

Signal for M15 bar i is decided at its CLOSE using only bars 0..i and the most
recent H4 bar that had already COMPLETED by that close. The backtester executes
the signal at the OPEN of bar i+1 (next realistically available price).

    LONG  : H4 close > H4 200-EMA  AND  M15 close crosses above M15 20-EMA
    SHORT : H4 close < H4 200-EMA  AND  M15 close crosses below M15 20-EMA
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from config import StrategyConfig
from data_manager import Bar
import indicators as ind


@dataclass
class Signals:
    direction: List[int]        # +1 long / -1 short / 0 none, decided at close of bar i
    atr: List[Optional[float]]  # M15 ATR at bar i
    ema: List[Optional[float]]  # M15 entry EMA at bar i
    h4_ema_at: List[Optional[float]]  # regime EMA applicable at bar i's close
    h4_close_at: List[Optional[float]]


def _h4_regime_pointer(m15: List[Bar], h4: List[Bar], h4_ema: List[Optional[float]]):
    """For each M15 bar, the (h4_close, h4_ema200) from the last H4 bar completed
    at or before that M15 bar's close. Returns two aligned lists."""
    closes = [None] * len(m15)
    emas = [None] * len(m15)
    j = -1
    for i, b in enumerate(m15):
        bar_close_ts = b.end_ts  # M15 close instant
        # advance j to the latest H4 bar whose end_ts <= bar_close_ts
        while j + 1 < len(h4) and h4[j + 1].end_ts <= bar_close_ts:
            j += 1
        if j >= 0 and h4_ema[j] is not None:
            closes[i] = h4[j].c
            emas[i] = h4_ema[j]
    return closes, emas


def build_signals(m15: List[Bar], h4: List[Bar], cfg: StrategyConfig) -> Signals:
    closes = [b.c for b in m15]
    highs = [b.h for b in m15]
    lows = [b.l for b in m15]
    ema_m15 = ind.ema(closes, cfg.entry_ema)
    atr_m15 = ind.atr(highs, lows, closes, cfg.atr_period)
    h4_ema = ind.ema([b.c for b in h4], cfg.htf_ema)
    h4_close_at, h4_ema_at = _h4_regime_pointer(m15, h4, h4_ema)

    direction = [0] * len(m15)
    for i in range(1, len(m15)):
        if ema_m15[i] is None or ema_m15[i - 1] is None:
            continue
        he, hc = h4_ema_at[i], h4_close_at[i]
        if he is None or hc is None:
            continue
        if cfg.entry_style == "pullback":
            # genuine buy-the-dip: price was already above the EMA (uptrend), this
            # bar's LOW pierced down to/through the EMA but the CLOSE held above it
            # — a pullback to the average that resumed, not a fresh cross.
            up = (closes[i - 1] > ema_m15[i - 1] and lows[i] <= ema_m15[i]
                  and closes[i] > ema_m15[i])
            dn = (closes[i - 1] < ema_m15[i - 1] and highs[i] >= ema_m15[i]
                  and closes[i] < ema_m15[i])
        else:  # baseline cross
            up = ind.crossed_up(closes[i - 1], ema_m15[i - 1], closes[i], ema_m15[i])
            dn = ind.crossed_down(closes[i - 1], ema_m15[i - 1], closes[i], ema_m15[i])
        if hc > he and up:
            direction[i] = 1
        elif hc < he and dn:
            direction[i] = -1
    return Signals(direction=direction, atr=atr_m15, ema=ema_m15,
                   h4_ema_at=h4_ema_at, h4_close_at=h4_close_at)
