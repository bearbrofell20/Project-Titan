"""Pre-registered hypothesis test + hostile audit (Parts 7-26).

Discipline: a SMALL, fixed set of hypotheses (the diagnosis pointed at exits), each
scored on an untouched VALIDATION slice. Model selection uses VALIDATION only; the
final OOS holdout is looked at once, for the single best candidate. Every run is
written to results/experiment_log.csv so multiple-testing bias is visible.
"""

from __future__ import annotations

import csv
import dataclasses as dc
import logging
import os

from config import Config
import data_manager as dm
import metrics
import monte_carlo
import validation as V
from strategy import build_signals
from backtester import simulate

logging.basicConfig(level=logging.INFO, format="%(message)s")
DATA = os.getenv("EURUSD_M15", "../market_data/EUR_USD_M15.json")

# Pre-registered hypotheses (name -> StrategyConfig field overrides). Diagnosis:
# the ATR trailing stop chops; overnight-survivors were the only positive bucket.
HYPOTHESES = {
    "H0_baseline":            dict(),
    "H1_notrail_hold_cutoff": dict(trail_atr_mult=0.0, target_r=0.0),
    "H2_fixed_2R_notrail":    dict(trail_atr_mult=0.0, target_r=2.0),
    "H3_breakeven_1R_trail":  dict(breakeven_at_r=1.0, trail_atr_mult=1.5),
    "H4_session_ny_overlap":  dict(sessions_utc=list(range(12, 20))),
    "H5_pullback_hold_cutoff":dict(entry_style="pullback", trail_atr_mult=0.0, target_r=0.0),
    "H6_wider_stop_2atr":     dict(stop_atr_mult=2.0, trail_atr_mult=0.0, target_r=0.0),
}


def run_one(m15, h4, cfg):
    sig = build_signals(m15, h4, cfg.strategy)
    trades = simulate(m15, sig, cfg.strategy, cfg.risk, cfg.cost)
    return trades


def main():
    base = Config()
    candles = dm.load_candles(DATA)
    m15 = dm.to_bars(candles, "M15")
    h4 = dm.resample_h4(m15)
    print(f"M15 bars={len(m15)}  {dm.utc(m15[0].ts)} -> {dm.utc(m15[-1].ts)}\n")

    os.makedirs("results", exist_ok=True)
    rows = []
    results = {}
    print(f"{'hypothesis':26s} {'IS exp':>8s} {'VALID exp':>9s} {'VALID PF':>8s} {'OOS exp':>8s} {'trades':>7s}")
    for name, over in HYPOTHESES.items():
        cfg = dc.replace(base, strategy=dc.replace(base.strategy, **over))
        trades = run_one(m15, h4, cfg)
        sl = V.evaluate_slices(m15, trades)
        results[name] = (cfg, trades, sl)
        print(f"{name:26s} {sl['IS']['expectancy_r']:+8.3f} {sl['VALID']['expectancy_r']:+9.3f} "
              f"{sl['VALID']['profit_factor']:>8} {sl['OOS']['expectancy_r']:+8.3f} {len(trades):>7d}")
        rows.append({
            "experiment_id": name, "params": str(over),
            "trades": len(trades),
            "IS_exp": sl["IS"]["expectancy_r"], "VALID_exp": sl["VALID"]["expectancy_r"],
            "VALID_pf": sl["VALID"]["profit_factor"], "OOS_exp": sl["OOS"]["expectancy_r"],
            "VALID_net_r": sl["VALID"]["net_r"],
        })
    with open("results/experiment_log.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)

    # ---- select on VALIDATION only ----
    best = max(results, key=lambda n: results[n][2]["VALID"]["expectancy_r"])
    bcfg, btrades, bsl = results[best]
    print(f"\nBest on VALIDATION: {best}  (VALID exp {bsl['VALID']['expectancy_r']:+.3f}R)")

    if bsl["VALID"]["expectancy_r"] <= 0:
        print("\n================= FINAL VERDICT =================")
        print("NO ROBUST EDGE FOUND — the best pre-registered hypothesis is NOT")
        print("positive even on the validation slice. Nothing advances to OOS.")
        return

    # ---- hostile audit of the single best (Parts 19,21,13,26) ----
    print(f"\n--- HOSTILE AUDIT of {best} ---")
    print("OOS (untouched holdout):", metrics.fmt(bsl["OOS"]))
    print("\nWalk-forward (5 windows):")
    for i, w in enumerate(V.walk_forward(m15, btrades, 5), 1):
        print(f"  w{i} {metrics.fmt(w)}")
    print("\nCost stress:")
    for mult, slp in [(1.0, 0.3), (1.5, 0.5), (2.0, 1.0)]:
        cfg = dc.replace(bcfg, cost=dc.replace(bcfg.cost, spread_mult=mult, slippage_pips=slp))
        t = run_one(m15, h4, cfg)
        print(f"  spread x{mult}, slip {slp}p: {metrics.fmt(metrics.summarize(t))}")
    print("\nMonte Carlo:", monte_carlo.run(btrades))


if __name__ == "__main__":
    main()
