"""Test the SMC stack on EUR/USD M15 with ablation + OOS + cost stress.

Ablation isolates each stage's contribution:
  A. sweep-only            (require_mss=False)
  B. sweep + MSS           (require_retest=False)
  C. sweep + MSS + retest  (full stack)
Exits are held constant (1.5xATR stop, 2R target) so we measure the ENTRY's edge.
"""

from __future__ import annotations

import dataclasses as dc
import os

from config import Config
import data_manager as dm
import metrics
from backtester import simulate
from smc import SMCParams, build_smc_signals

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


def main():
    base = Config()
    scfg = dc.replace(base.strategy, instrument="EUR_USD",
                      stop_atr_mult=1.5, target_r=2.0, trail_atr_mult=0.0,
                      overnight_cutoff_hour_utc=None, sessions_utc=[])
    bars = dm.to_bars(dm.load_candles(DATA), "M15")
    print(f"EUR/USD M15: {len(bars)} bars  {dm.utc(bars[0].ts)} -> {dm.utc(bars[-1].ts)}\n")

    variants = {
        "A_sweep_only":       SMCParams(require_mss=False, require_retest=False),
        "B_sweep_mss":        SMCParams(require_mss=True, require_retest=False),
        "C_sweep_mss_retest": SMCParams(require_mss=True, require_retest=True),
    }
    print(f"{'variant':22s} {'trades':>6} {'ALL exp':>8} {'ALL PF':>7} {'IS':>7} {'VALID':>7} {'OOS':>7}")
    best = None
    for name, p in variants.items():
        sig = build_smc_signals(bars, p)
        trades = simulate(bars, sig, scfg, base.risk, base.cost)
        sl = split(trades)
        allm = metrics.summarize(trades)
        row = (allm["expectancy_r"], allm["profit_factor"],
               metrics.summarize(sl["IS"])["expectancy_r"],
               metrics.summarize(sl["VALID"])["expectancy_r"],
               metrics.summarize(sl["OOS"])["expectancy_r"])
        print(f"{name:22s} {len(trades):>6} {row[0]:>+8.3f} {row[1]:>7} "
              f"{row[2]:>+7.3f} {row[3]:>+7.3f} {row[4]:>+7.3f}")
        if best is None or row[3] > best[1]:
            best = (name, row[3], trades, sl)

    name, vexp, trades, sl = best
    print(f"\nBest on VALIDATION: {name} (VALID exp {vexp:+.3f}R)")
    if vexp <= 0:
        print("\n===== VERDICT: NO EDGE — best SMC variant is not positive on validation. =====")
        return
    print("OOS:", metrics.fmt(metrics.summarize(sl["OOS"])))
    print("\ncost stress on best:")
    scfg2 = scfg
    for mult, slp in [(1.0, 0.3), (1.5, 0.5), (2.0, 1.0)]:
        c = dc.replace(base, cost=dc.replace(base.cost, spread_mult=mult, slippage_pips=slp))
        p = variants[name]
        t = simulate(bars, build_smc_signals(bars, p), scfg2, c.risk, c.cost)
        print(f"  spread x{mult}, slip {slp}p: {metrics.fmt(metrics.summarize(t))}")


if __name__ == "__main__":
    main()
