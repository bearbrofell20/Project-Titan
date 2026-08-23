"""Regime hypothesis: does gating each family to its 'right' regime beat running
it blind? trend->trending, mean-reversion->range, breakout->vol-expansion.
Measured on EUR/USD M15, ATR exits, IS/VALID/OOS."""

from __future__ import annotations

import dataclasses as dc
import os

from config import Config
import data_manager as dm
import families as F
import indicators as ind
import metrics
from backtester import simulate
from regime import classify
from strategy import Signals

DATA = os.getenv("EURUSD_M15", "../market_data/EUR_USD_M15.json")


def split(trades, fracs=(0.6, 0.2, 0.2)):
    if not trades:
        return {"IS": [], "VALID": [], "OOS": []}
    t0, t1 = trades[0].entry_ts, trades[-1].entry_ts
    span = max(1, t1 - t0)
    b1, b2 = t0 + span * fracs[0], t0 + span * (fracs[0] + fracs[1])
    return {"IS": [t for t in trades if t.entry_ts < b1],
            "VALID": [t for t in trades if b1 <= t.entry_ts < b2],
            "OOS": [t for t in trades if t.entry_ts >= b2]}


def run(bars, scfg, cfg, direction):
    atr = ind.atr([b.h for b in bars], [b.l for b in bars], [b.c for b in bars], 14)
    sig = Signals(direction=direction, atr=atr, ema=[None] * len(bars),
                  h4_ema_at=[None] * len(bars), h4_close_at=[None] * len(bars))
    return simulate(bars, sig, scfg, cfg.risk, cfg.cost)


def show(label, bars, scfg, cfg, direction):
    tr = run(bars, scfg, cfg, direction)
    sl = split(tr)
    a = metrics.summarize(tr)
    print(f"{label:34s} n={a['trades']:>5} ALL={a['expectancy_r']:+.3f} PF={a['profit_factor']:>5} "
          f"IS={metrics.summarize(sl['IS'])['expectancy_r']:+.3f} "
          f"VAL={metrics.summarize(sl['VALID'])['expectancy_r']:+.3f} "
          f"OOS={metrics.summarize(sl['OOS'])['expectancy_r']:+.3f}")


def main():
    cfg = Config()
    scfg = dc.replace(cfg.strategy, instrument="EUR_USD", stop_atr_mult=1.5,
                      target_r=2.0, trail_atr_mult=0.0, overnight_cutoff_hour_utc=None,
                      sessions_utc=[])
    bars = dm.to_bars(dm.load_candles(DATA), "M15")
    rg = classify(bars)
    print(f"EUR/USD M15 {len(bars)} bars\n")
    trend = F.trend_cross(bars)
    mr = F.mean_reversion(bars)
    bo = F.breakout(bars)

    print("--- TREND family ---")
    show("trend: unconditional", bars, scfg, cfg, trend)
    show("trend: gated to trending+aligned", bars, scfg, cfg,
         [d if (d == 1 and rg.label[i] == "trend_up") or (d == -1 and rg.label[i] == "trend_down")
          else 0 for i, d in enumerate(trend)])

    print("\n--- MEAN-REVERSION family ---")
    show("meanrev: unconditional", bars, scfg, cfg, mr)
    show("meanrev: gated to range", bars, scfg, cfg,
         F.gate(mr, lambda i: rg.label[i] == "range"))

    print("\n--- BREAKOUT family ---")
    show("breakout: unconditional", bars, scfg, cfg, bo)
    show("breakout: gated to expansion", bars, scfg, cfg,
         F.gate(bo, lambda i: rg.expansion[i]))


if __name__ == "__main__":
    main()
