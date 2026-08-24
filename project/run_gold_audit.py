"""Hostile audit of the GOLD breakout candidate (XAU_USD H1).
Parameter robustness, walk-forward, cost stress, Monte Carlo, long/short split —
the same brutal test that broke the JPY candidate. Fresh eyes, try to kill it."""

from __future__ import annotations

import dataclasses as dc
import os

from config import Config
import data_manager as dm
import families as F
import indicators as ind
import metrics
import monte_carlo
from backtester import simulate
from strategy import Signals

DATA = os.getenv("XAU_H1", "../market_data/XAU_USD_H1.json")


def split(trades, fracs=(0.6, 0.2, 0.2)):
    if not trades:
        return {"IS": [], "VALID": [], "OOS": []}
    t0, t1 = trades[0].entry_ts, trades[-1].entry_ts
    span = max(1, t1 - t0)
    b1, b2 = t0 + span * fracs[0], t0 + span * (fracs[0] + fracs[1])
    return {"IS": [t for t in trades if t.entry_ts < b1],
            "VALID": [t for t in trades if b1 <= t.entry_ts < b2],
            "OOS": [t for t in trades if t.entry_ts >= b2]}


def walk(trades, w=6):
    if not trades:
        return []
    t0, t1 = trades[0].entry_ts, trades[-1].entry_ts
    span = max(1, t1 - t0)
    out = []
    for k in range(w):
        lo, hi = t0 + span * k / w, t0 + span * (k + 1) / w
        out.append(metrics.summarize([t for t in trades if lo <= t.entry_ts < hi]))
    return out


def sig_from(bars, direction):
    atr = ind.atr([b.h for b in bars], [b.l for b in bars], [b.c for b in bars], 14)
    return Signals(direction=direction, atr=atr, ema=[None] * len(bars),
                   h4_ema_at=[None] * len(bars), h4_close_at=[None] * len(bars))


def run(bars, scfg, cfg, lookback, target_r=2.0, stop=1.5):
    s = dc.replace(scfg, target_r=target_r, stop_atr_mult=stop)
    return simulate(bars, sig_from(bars, F.breakout(bars, lookback)), s, cfg.risk, cfg.cost)


def main():
    cfg = Config()
    scfg = dc.replace(cfg.strategy, instrument="XAU_USD", stop_atr_mult=1.5,
                      target_r=2.0, trail_atr_mult=0.0, overnight_cutoff_hour_utc=None,
                      sessions_utc=[])
    bars = dm.to_bars(dm.load_candles(DATA), "H1")
    print(f"GOLD XAU_USD H1: {len(bars)} bars  {dm.utc(bars[0].ts)} -> {dm.utc(bars[-1].ts)}\n")

    print("1) PARAMETER ROBUSTNESS — breakout lookback (stable region?)")
    print(f"   {'lookback':>8} {'n':>5} {'ALL':>7} {'PF':>5} {'IS':>7} {'VAL':>7} {'OOS':>7}")
    for lb in (15, 20, 25, 30, 40, 50, 60):
        tr = run(bars, scfg, cfg, lb)
        sl = split(tr); a = metrics.summarize(tr)
        print(f"   {lb:>8} {a['trades']:>5} {a['expectancy_r']:>+7.3f} {a['profit_factor']:>5} "
              f"{metrics.summarize(sl['IS'])['expectancy_r']:>+7.3f} "
              f"{metrics.summarize(sl['VALID'])['expectancy_r']:>+7.3f} "
              f"{metrics.summarize(sl['OOS'])['expectancy_r']:>+7.3f}")

    tr = run(bars, scfg, cfg, 40)
    print(f"\n2) FLAGSHIP breakout 40: {metrics.fmt(metrics.summarize(tr))}")

    print("\n3) WALK-FORWARD (6 windows):")
    pos = 0
    for i, w in enumerate(walk(tr, 6), 1):
        pos += 1 if w.get('expectancy_r', 0) > 0 else 0
        print(f"   w{i} {metrics.fmt(w)}")
    print(f"   -> {pos}/6 windows positive")

    print("\n4) COST STRESS (breakout 40):")
    for mult, slp in [(1.0, 0.3), (1.5, 0.5), (2.0, 1.0), (3.0, 2.0)]:
        c = dc.replace(cfg, cost=dc.replace(cfg.cost, spread_mult=mult, slippage_pips=slp))
        t = simulate(bars, sig_from(bars, F.breakout(bars, 40)), scfg, c.risk, c.cost)
        print(f"   spread x{mult}, slip {slp}: {metrics.fmt(metrics.summarize(t))}")

    print("\n5) LONG vs SHORT (breakout 40):")
    longs = [t for t in tr if t.direction == 1]
    shorts = [t for t in tr if t.direction == -1]
    print(f"   long : {metrics.fmt(metrics.summarize(longs))}")
    print(f"   short: {metrics.fmt(metrics.summarize(shorts))}")

    print("\n6) MONTE CARLO (breakout 40):", monte_carlo.run(tr))


if __name__ == "__main__":
    main()
