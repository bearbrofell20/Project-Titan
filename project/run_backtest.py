"""Run the baseline (Part 5) and print the diagnosis (Part 6)."""

from __future__ import annotations

import logging
import os
import sys
from collections import defaultdict

from config import Config
import data_manager as dm
import metrics
from strategy import build_signals
from backtester import simulate, _session

logging.basicConfig(level=logging.INFO, format="%(message)s")
DATA = os.getenv("EURUSD_M15", "../market_data/EUR_USD_M15.json")


def load():
    candles = dm.load_candles(DATA)
    report = dm.validate(candles, dm.TF_SECONDS["M15"])
    print(f"DATA: {report}")
    m15 = dm.to_bars(candles, "M15")
    h4 = dm.resample_h4(m15)
    print(f"M15 bars={len(m15)}  {dm.utc(m15[0].ts)} -> {dm.utc(m15[-1].ts)}  |  H4 bars={len(h4)}")
    return m15, h4


def diagnose(trades):
    print("\n--- DIAGNOSIS (Part 6) ---")
    for keyname, keyfn in [
        ("session", lambda t: _session(t.entry_hour)),
        ("exit reason", lambda t: t.reason),
        ("direction", lambda t: "long" if t.direction == 1 else "short"),
    ]:
        buckets = defaultdict(list)
        for t in trades:
            buckets[keyfn(t)].append(t)
        print(f"\nby {keyname}:")
        for k in sorted(buckets):
            print(f"  {k:10s}{metrics.fmt(metrics.summarize(buckets[k]))}")
    # by hour
    print("\nby entry hour (UTC):")
    byh = defaultdict(list)
    for t in trades:
        byh[t.entry_hour].append(t)
    for h in sorted(byh):
        s = metrics.summarize(byh[h])
        print(f"  {h:02d}h  n={s['trades']:4d}  exp={s['expectancy_r']:+.3f}R  PF={s['profit_factor']}")


def main():
    cfg = Config()
    m15, h4 = load()
    sig = build_signals(m15, h4, cfg.strategy)
    trades = simulate(m15, sig, cfg.strategy, cfg.risk, cfg.cost)
    print("\n=== BASELINE (H4 200-EMA regime + M15 20-EMA cross, 1.5 ATR stop, ATR trail) ===")
    print(metrics.fmt(metrics.summarize(trades)))
    n_sig = sum(1 for d in sig.direction if d != 0)
    print(f"raw signals={n_sig}  trades taken={len(trades)}")
    diagnose(trades)


if __name__ == "__main__":
    main()
