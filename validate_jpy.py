"""Validate the JPY-cross trend edge — the first positive forex result in Titan.

Reproduces the finding in AUDIT.md: ema_trend 20/60 (stop 30 / target 75 pips)
on AUD_JPY + EUR_JPY (H1) is positive across in-sample, out-of-sample, and
holdout, in every one of 6 walk-forward windows, and on each pair separately.
The same strategy has NO edge on the USD majors (AUD_USD, EUR_USD) — including
them dilutes the basket back to break-even.

    python yahoo_data.py AUD_JPY EUR_JPY AUD_USD EUR_USD   # get data first
    python validate_jpy.py

Data is Yahoo hourly mid with a synthetic constant spread — a positive result
here is a *candidate*, confirmed only by live paper trading on real bid/ask.
"""

from __future__ import annotations

import random

import bt
import metrics
import validate as V
from oanda_trader import Config

EDGE = ["AUD_JPY", "EUR_JPY"]
MAJORS = ["AUD_USD", "EUR_USD"]
COSTS = bt.Costs(slippage_pips=0.3, commission_usd=0.0)


def _run(pairs, fast=20, slow=60, stop=30, target=75):
    Config.TREND_FAST, Config.TREND_SLOW = fast, slow
    exits = bt.ExitConfig(stop_pips=stop, target_pips=target)
    return V.run("ema_trend", exits=exits, costs=COSTS, pairs=pairs,
                 gran="H1", days=1100, trend_filter=True)["pooled"]


def _line(tag, tr):
    s = metrics.summarize(tr)
    print(f"  {tag:10s} n={s['trades']:4d}  exp={s['expectancy_r']:+.3f}R  "
          f"PF={s['profit_factor']:.2f}  win={s['win_rate']:.0f}%")


def main():
    p = _run(EDGE)
    sp = V.split_chrono(p)
    print("=== ema_trend 20/60, stop30/tgt75, H1 — AUD_JPY + EUR_JPY ===")
    for tag, tr in (("ALL", p), ("IS", sp["IS"]), ("OOS", sp["OOS"]),
                    ("HOLDOUT", sp["HOLDOUT"])):
        _line(tag, tr)
    print("\nper pair:")
    for inst in EDGE:
        _line(inst, _run([inst]))
    print("\nwalk-forward (6 windows):")
    for i, w in enumerate(V.walk_forward(p, 6), 1):
        mark = "+" if w["expectancy_r"] > 0 else "-"
        print(f"  w{i} [{mark}] n={w['trades']:3d} exp={w['expectancy_r']:+.3f}R "
              f"PF={w['profit_factor']:.2f}")

    rs = [t.r_multiple for t in p]
    sims = sorted(sum(random.choice(rs) for _ in range(len(rs)))
                  for _ in range(5000))
    print(f"\nMonte Carlo (5000x bootstrap of {len(rs)} trades):")
    print(f"  realized {sum(rs):+.1f}R  P(total>0)={sum(x>0 for x in sims)/50:.0f}%"
          f"  5th pct {sims[250]:+.1f}R")

    print("\ncontrol — same strategy on USD majors (should be flat/negative):")
    _line("AUD+EUR/USD", _run(MAJORS))
    _line("all 4 pairs", _run(EDGE + MAJORS))


if __name__ == "__main__":
    main()
