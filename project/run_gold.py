"""Test the strategy families on GOLD (XAU_USD, H1) with the strict harness.
Gold is a different regime than FX majors (trending, macro-driven) — the FX
'no edge' result does not automatically transfer, so test it honestly."""

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
from regime import classify
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


def sig_from(bars, direction):
    atr = ind.atr([b.h for b in bars], [b.l for b in bars], [b.c for b in bars], 14)
    return Signals(direction=direction, atr=atr, ema=[None] * len(bars),
                   h4_ema_at=[None] * len(bars), h4_close_at=[None] * len(bars))


def show(label, bars, scfg, cfg, direction):
    tr = simulate(bars, sig_from(bars, direction), scfg, cfg.risk, cfg.cost)
    sl = split(tr); a = metrics.summarize(tr)
    print(f"{label:26s} n={a['trades']:>5} ALL={a['expectancy_r']:+.3f} PF={a['profit_factor']:>5} "
          f"IS={metrics.summarize(sl['IS'])['expectancy_r']:+.3f} "
          f"VAL={metrics.summarize(sl['VALID'])['expectancy_r']:+.3f} "
          f"OOS={metrics.summarize(sl['OOS'])['expectancy_r']:+.3f}")
    return tr


def main():
    cfg = Config()
    scfg = dc.replace(cfg.strategy, instrument="XAU_USD", stop_atr_mult=1.5,
                      target_r=2.0, trail_atr_mult=0.0, overnight_cutoff_hour_utc=None,
                      sessions_utc=[])
    bars = dm.to_bars(dm.load_candles(DATA), "H1")
    print(f"GOLD XAU_USD H1: {len(bars)} bars  {dm.utc(bars[0].ts)} -> {dm.utc(bars[-1].ts)}\n")

    best = None
    for label, d in [("trend 20/60", F.trend_cross(bars, 20, 60)),
                     ("trend 50/100", F.trend_cross(bars, 50, 100)),
                     ("breakout 20", F.breakout(bars, 20)),
                     ("breakout 40", F.breakout(bars, 40)),
                     ("mean-reversion", F.mean_reversion(bars))]:
        tr = show(label, bars, scfg, cfg, d)
        vexp = metrics.summarize(split(tr)["VALID"])["expectancy_r"]
        if best is None or vexp > best[1]:
            best = (label, vexp, tr)

    name, vexp, tr = best
    print(f"\nBest on VALIDATION: {name} ({vexp:+.3f}R)")
    if vexp <= 0:
        print("===== No family positive on validation. =====")
        return
    print("OOS:", metrics.fmt(metrics.summarize(split(tr)["OOS"])))
    print("cost stress:")
    for mult, slp in [(1.0, 0.3), (1.5, 0.5), (2.0, 1.0)]:
        c = dc.replace(cfg, cost=dc.replace(cfg.cost, spread_mult=mult, slippage_pips=slp))
        d = {"trend 20/60": F.trend_cross(bars, 20, 60), "trend 50/100": F.trend_cross(bars, 50, 100),
             "breakout 20": F.breakout(bars, 20), "breakout 40": F.breakout(bars, 40),
             "mean-reversion": F.mean_reversion(bars)}[name]
        t = simulate(bars, sig_from(bars, d), scfg, c.risk, c.cost)
        print(f"  spread x{mult}, slip {slp}: {metrics.fmt(metrics.summarize(t))}")
    print("Monte Carlo:", monte_carlo.run(tr))


if __name__ == "__main__":
    main()
