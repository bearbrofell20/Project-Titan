"""Performance metrics (Part 17). All expectancy/averages are in R (risk units)."""

from __future__ import annotations

import math
from typing import Dict, List, Sequence


def _std(xs: Sequence[float]) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    m = sum(xs) / n
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))


def summarize(trades: List, starting_equity: float = 100_000.0) -> Dict[str, float]:
    n = len(trades)
    if n == 0:
        return {"trades": 0, "expectancy_r": 0.0, "profit_factor": 0.0,
                "win_rate": 0.0, "net_r": 0.0, "net_usd": 0.0, "max_dd_r": 0.0}
    rs = [t.r_multiple for t in trades]
    pnl = [t.pnl_usd for t in trades]
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    gross_win = sum(r for r in rs if r > 0)
    gross_loss = -sum(r for r in rs if r < 0)
    pf = (gross_win / gross_loss) if gross_loss > 0 else float("inf")

    # equity path in R for drawdown/streaks
    eq, peak, max_dd = 0.0, 0.0, 0.0
    cur_streak = worst_streak = 0
    for r in rs:
        eq += r
        peak = max(peak, eq)
        max_dd = max(max_dd, peak - eq)
        if r <= 0:
            cur_streak += 1
            worst_streak = max(worst_streak, cur_streak)
        else:
            cur_streak = 0

    exp = sum(rs) / n
    sharpe = (exp / _std(rs) * math.sqrt(n)) if _std(rs) > 0 else 0.0
    downside = _std([min(0.0, r) for r in rs])
    sortino = (exp / downside * math.sqrt(n)) if downside > 0 else 0.0
    durations = [t.bars_held for t in trades]

    return {
        "trades": n,
        "win_rate": round(100.0 * len(wins) / n, 1),
        "gross_profit_r": round(gross_win, 2),
        "gross_loss_r": round(gross_loss, 2),
        "net_r": round(sum(rs), 2),
        "net_usd": round(sum(pnl), 2),
        "profit_factor": round(pf, 3) if pf != float("inf") else 999.0,
        "expectancy_r": round(exp, 4),
        "avg_winner_r": round(sum(wins) / len(wins), 3) if wins else 0.0,
        "avg_loser_r": round(sum(losses) / len(losses), 3) if losses else 0.0,
        "max_dd_r": round(max_dd, 2),
        "return_over_dd": round(sum(rs) / max_dd, 2) if max_dd > 0 else 0.0,
        "sharpe": round(sharpe, 2),
        "sortino": round(sortino, 2),
        "max_consec_losses": worst_streak,
        "avg_bars_held": round(sum(durations) / n, 1),
        "avg_mae_r": round(sum(t.mae_r for t in trades) / n, 3),
        "avg_mfe_r": round(sum(t.mfe_r for t in trades) / n, 3),
    }


def fmt(s: Dict[str, float]) -> str:
    if s.get("trades", 0) == 0:
        return "  (no trades)"
    return (f"  trades={s['trades']}  exp={s['expectancy_r']:+.4f}R  PF={s['profit_factor']}  "
            f"win={s['win_rate']}%  net={s['net_r']:+.1f}R  maxDD={s['max_dd_r']:.1f}R  "
            f"PFret/DD={s['return_over_dd']}  Sharpe={s['sharpe']}  streak={s['max_consec_losses']}")
