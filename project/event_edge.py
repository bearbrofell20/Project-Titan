"""A DIFFERENT signal class: post-release momentum (event-driven, not indicator).

Hypothesis: major US data drops at 12:30 UTC (NFP, CPI, retail sales, etc.). If a
release is a genuine surprise, the 12:30 M15 bar makes an outsized move; the
question is whether price KEEPS going (drift we can catch) in the hour after, or
whether it's already fully priced (no edge).

Test: after the 12:30 bar completes, if |its move| > k*ATR (a real reaction),
enter at the 12:45 open in the direction of the move; exit after `hold` bars.
Realistic bid/ask fills + slippage. Measured in R vs a fixed stop.
"""

from __future__ import annotations

import datetime as dt
import os

import data_manager as dm
from config import pip_size

DATA = os.getenv("EURUSD_M15", "../market_data/EUR_USD_M15.json")
PIP = pip_size("EUR_USD")


def atr_at(bars, i, period=14):
    if i < period:
        return None
    trs = []
    for j in range(i - period + 1, i + 1):
        pc = bars[j - 1].c
        trs.append(max(bars[j].h - bars[j].l, abs(bars[j].h - pc), abs(bars[j].l - pc)))
    return sum(trs) / period


def collect(k_atr: float, hold: int, fade: bool, slippage_pips=0.3):
    bars = dm.to_bars(dm.load_candles(DATA), "M15")
    slip = slippage_pips * PIP
    trades = []  # (entry_ts, r)
    for i, b in enumerate(bars):
        t = dt.datetime.utcfromtimestamp(b.ts)
        if not (t.hour == 12 and t.minute == 30):
            continue
        a = atr_at(bars, i)
        if not a or a <= 0:
            continue
        move = b.c - b.o
        if abs(move) < k_atr * a:
            continue
        d = (-1 if move > 0 else 1) if fade else (1 if move > 0 else -1)
        entry_i, exit_i = i + 1, i + hold
        if exit_i >= len(bars) or entry_i >= len(bars):
            continue
        eb, xb = bars[entry_i], bars[exit_i]
        entry = eb.o + d * ((eb.ask_c - eb.bid_c) / 2.0 + slip)
        exit_px = xb.c - d * ((xb.ask_c - xb.bid_c) / 2.0 + slip)
        risk = k_atr * a
        trades.append((eb.ts, d * (exit_px - entry) / risk))
    return trades


def stats(rs):
    if not rs:
        return None
    n = len(rs); wins = [x for x in rs if x > 0]
    gp = sum(x for x in rs if x > 0); gl = -sum(x for x in rs if x < 0)
    pf = gp / gl if gl > 0 else 999.0
    return {"n": n, "exp_r": round(sum(rs) / n, 3), "pf": round(pf, 2),
            "win": round(100 * len(wins) / n, 1)}


def split_oos(trades, frac=0.7):
    if not trades:
        return [], []
    trades.sort()
    cut = trades[int(len(trades) * frac)][0]
    return ([r for ts, r in trades if ts < cut], [r for ts, r in trades if ts >= cut])


if __name__ == "__main__":
    print("FADE the 12:30-UTC release spike on EUR/USD M15 (in-sample -> out-of-sample)")
    print(f"{'k*ATR':>6} {'hold':>5} {'IS n':>5} {'IS exp':>7} {'IS PF':>6} | {'OOS n':>5} {'OOS exp':>8} {'OOS PF':>6}")
    for k in (0.5, 1.0, 1.5):
        for hold in (2, 4, 8):
            tr = collect(k, hold, fade=True)
            is_, oos = split_oos(tr)
            si, so = stats(is_), stats(oos)
            if si and so:
                print(f"{k:>6} {hold:>5} {si['n']:>5} {si['exp_r']:>+7} {si['pf']:>6} | "
                      f"{so['n']:>5} {so['exp_r']:>+8} {so['pf']:>6}")
