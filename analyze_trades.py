#!/usr/bin/env python3
"""Honest scorecard for the live bot — reads the closed-trade ledger.

    python analyze_trades.py [path/to/closed_trades.jsonl]

Answers the one question that matters when the account is red:
**is this bad luck, or a bad strategy?**

It does that with statistics rather than vibes:
  * Wilson confidence interval on the win rate (valid for small samples)
  * Bootstrap confidence interval on expectancy
  * The sample size actually required to distinguish this edge from zero

The most common finding on a young account is "not enough trades to conclude
anything" — which is a real answer, not a dodge, and it is the antidote to
panicking at noise.
"""

from __future__ import annotations

import json
import math
import random
import sys
from collections import defaultdict
from pathlib import Path

DEFAULT = Path("trade_logs") / "closed_trades.jsonl"


def load(path: Path):
    if not path.exists():
        print(f"No ledger at {path}.")
        print("The bot writes it once trades close. If this is a fresh deploy, wait for closes.")
        return []
    rows = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    return rows


def wilson(wins: int, n: int, z: float = 1.96):
    """Wilson score interval — trustworthy for small n, unlike the normal approx."""
    if n == 0:
        return (0.0, 0.0)
    p = wins / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, centre - half) * 100, min(1.0, centre + half) * 100)


def bootstrap_ci(values, sims: int = 10000, seed: int = 7):
    """Percentile CI for the mean — no distributional assumptions."""
    if not values:
        return (0.0, 0.0)
    random.seed(seed)
    n = len(values)
    means = sorted(sum(random.choice(values) for _ in range(n)) / n for _ in range(sims))
    return (means[int(0.025 * sims)], means[int(0.975 * sims)])


def trades_needed(mean: float, sd: float) -> int | None:
    """Roughly how many trades to distinguish this edge from zero (95%, ~80% power)."""
    if mean == 0 or sd == 0:
        return None
    return int(math.ceil((2.8 * sd / abs(mean)) ** 2))


def main(argv):
    path = Path(argv[0]) if argv else DEFAULT
    rows = load(path)
    if not rows:
        return 1

    pls = [r["realized_pl"] for r in rows]
    rs = [r["r_multiple"] for r in rows]
    n = len(rows)
    wins = [p for p in pls if p > 0]
    losses = [p for p in pls if p < 0]
    gw, gl = sum(wins), -sum(losses)

    print("=" * 62)
    print(f"LIVE SCORECARD — {n} closed trades")
    print("=" * 62)
    print(f"  Net P/L        : ${sum(pls):+,.2f}")
    print(f"  Win rate       : {100*len(wins)/n:.1f}%  ({len(wins)}W / {len(losses)}L)")
    lo, hi = wilson(len(wins), n)
    print(f"    95% CI       : {lo:.1f}% – {hi:.1f}%   <- true win rate lives in here")
    print(f"  Avg win        : ${gw/len(wins):+,.2f}" if wins else "  Avg win        : n/a")
    print(f"  Avg loss       : ${-gl/len(losses):+,.2f}" if losses else "  Avg loss       : n/a")
    print(f"  Profit factor  : {gw/gl:.3f}" if gl > 0 else "  Profit factor  : n/a (no losses)")
    mean_r = sum(rs) / n
    print(f"  Expectancy     : {mean_r:+.4f} R per trade")
    rlo, rhi = bootstrap_ci(rs)
    print(f"    95% CI       : {rlo:+.3f} – {rhi:+.3f} R")

    # --- the verdict: luck or edge? ---
    sd = (sum((x - mean_r) ** 2 for x in rs) / (n - 1)) ** 0.5 if n > 1 else 0.0
    need = trades_needed(mean_r, sd)
    print("\n" + "-" * 62)
    print("VERDICT")
    print("-" * 62)
    if rlo <= 0 <= rhi:
        print("  STATISTICALLY INCONCLUSIVE — this result is consistent with zero edge.")
        print("  The confidence interval straddles 0, so the current P/L (up OR down)")
        print("  cannot be distinguished from random noise. Do not act on it.")
        if need:
            print(f"  To tell this edge from luck you would need ~{need:,} trades"
                  f" (you have {n}).")
    elif rhi < 0:
        print("  GENUINELY NEGATIVE — the whole confidence interval is below zero.")
        print("  This is not bad luck. The strategy is losing money systematically.")
    else:
        print("  GENUINELY POSITIVE — the whole confidence interval is above zero.")
        print("  Evidence of a real edge at this sample size. Keep going, stay honest.")

    # --- per instrument ---
    by = defaultdict(list)
    for r in rows:
        by[r.get("instrument", "?")].append(r)
    if len(by) > 1:
        print("\nBY INSTRUMENT")
        for inst in sorted(by, key=lambda k: -sum(x["realized_pl"] for x in by[k])):
            g = by[inst]
            w = sum(1 for x in g if x["realized_pl"] > 0)
            print(f"  {inst:12s} n={len(g):>3}  net ${sum(x['realized_pl'] for x in g):+9,.2f}"
                  f"  win {100*w/len(g):.0f}%")

    print("\nNote: a small sample is the normal state of a young account. "
          "'Inconclusive'\nis the honest answer, not a failure — and it is the"
          " correct reason NOT to\npanic at a red number or celebrate a green one.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
