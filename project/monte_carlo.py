"""Monte Carlo on the trade sequence (Part 21).

Bootstrap-resample the realized R-multiples (with replacement) to ask: how much
of the result is order/luck? Reports the distribution of total return, drawdown,
and worst losing streak, plus a crude probability-of-ruin.
"""

from __future__ import annotations

import random
from typing import Dict, List


def _path_stats(rs: List[float]):
    eq = peak = maxdd = 0.0
    streak = worst = 0
    for r in rs:
        eq += r
        peak = max(peak, eq)
        maxdd = max(maxdd, peak - eq)
        if r <= 0:
            streak += 1
            worst = max(worst, streak)
        else:
            streak = 0
    return eq, maxdd, worst


def run(trades, n_sims: int = 5000, ruin_r: float = 100.0, seed: int = 7) -> Dict:
    rs = [t.r_multiple for t in trades]
    if not rs:
        return {"sims": 0}
    random.seed(seed)
    totals, dds, streaks, ruins = [], [], [], 0
    for _ in range(n_sims):
        sample = [random.choice(rs) for _ in rs]
        tot, dd, worst = _path_stats(sample)
        totals.append(tot); dds.append(dd); streaks.append(worst)
        if dd >= ruin_r:
            ruins += 1
    totals.sort(); dds.sort(); streaks.sort()
    def pct(xs, p):
        return round(xs[int(p * (len(xs) - 1))], 1)
    return {
        "sims": n_sims,
        "median_return_r": pct(totals, 0.50),
        "p5_return_r": pct(totals, 0.05),
        "p95_return_r": pct(totals, 0.95),
        "prob_total_positive": round(sum(1 for x in totals if x > 0) / n_sims, 3),
        "median_dd_r": pct(dds, 0.50),
        "p95_dd_r": pct(dds, 0.95),
        "worst_streak_p95": pct([float(s) for s in streaks], 0.95),
        "prob_dd_ge_%d_r" % int(ruin_r): round(ruins / n_sims, 3),
    }
