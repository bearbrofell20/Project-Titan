"""Test the key-level reaction strategy on M15 (primary) and M5 (thin sample).
Structure stops (beyond the rejection wick), 2R target. Ablation on which level
sets are used, plus IS/VALID/OOS + cost stress."""

from __future__ import annotations

import dataclasses as dc
import os

from config import Config
import data_manager as dm
import metrics
from backtester import simulate
import key_levels as KL


def split(trades, fracs=(0.6, 0.2, 0.2)):
    if not trades:
        return {"IS": [], "VALID": [], "OOS": []}
    t0, t1 = trades[0].entry_ts, trades[-1].entry_ts
    span = max(1, t1 - t0)
    b1, b2 = t0 + span * fracs[0], t0 + span * (fracs[0] + fracs[1])
    return {"IS": [t for t in trades if t.entry_ts < b1],
            "VALID": [t for t in trades if b1 <= t.entry_ts < b2],
            "OOS": [t for t in trades if t.entry_ts >= b2]}


def evaluate(path, tf, cfg, scfg, tol):
    bars = dm.to_bars(dm.load_candles(path), tf)
    sig = KL.reaction_signals(bars, tol_atr=tol)
    trades = simulate(bars, sig, scfg, cfg.risk, cfg.cost)
    sl = split(trades)
    a = metrics.summarize(trades)
    print(f"  {tf} tol={tol}: n={a['trades']:>5} ALL={a['expectancy_r']:+.3f} PF={a['profit_factor']:>5} "
          f"IS={metrics.summarize(sl['IS'])['expectancy_r']:+.3f} "
          f"VAL={metrics.summarize(sl['VALID'])['expectancy_r']:+.3f} "
          f"OOS={metrics.summarize(sl['OOS'])['expectancy_r']:+.3f}")
    return trades


def main():
    cfg = Config()
    scfg = dc.replace(cfg.strategy, instrument="EUR_USD", target_r=2.0,
                      trail_atr_mult=0.0, overnight_cutoff_hour_utc=None, sessions_utc=[])
    print("KEY-LEVEL REACTION (fade rejection at prev session/H1/H4/day levels)\n")
    print("EUR/USD M15 (1.6y real bid/ask) — primary:")
    for tol in (0.05, 0.10, 0.20):
        evaluate(os.getenv("EURUSD_M15", "../market_data/EUR_USD_M15.json"), "M15", cfg, scfg, tol)
    print("\nEUR/USD M5 (120d real bid/ask — THIN sample, directional only):")
    for tol in (0.05, 0.10, 0.20):
        evaluate("../market_data/EUR_USD_M5.json", "M5", cfg, scfg, tol)


if __name__ == "__main__":
    main()
