"""Performance metrics for a list of :class:`bt.Trade`.

Everything is expressed in **R** (multiples of the risk taken on each trade) so
results are comparable across pairs and position sizes. Expectancy — the average
R per trade — is the headline number: a strategy is only worth trading if its
expectancy is reliably positive *after* costs.
"""

from __future__ import annotations

import math
from typing import Dict, List

from bt import Trade


def _streaks(rs: List[float]):
    win = loss = cur = 0
    sign = 0
    for r in rs:
        s = 1 if r > 0 else (-1 if r < 0 else 0)
        cur = cur + 1 if s == sign and s != 0 else (1 if s != 0 else 0)
        sign = s
        if s > 0:
            win = max(win, cur)
        elif s < 0:
            loss = max(loss, cur)
    return win, loss


def summarize(trades: List[Trade]) -> Dict[str, float]:
    n = len(trades)
    if n == 0:
        return {"trades": 0, "expectancy_r": 0.0, "profit_factor": 0.0,
                "win_rate": 0.0, "net_r": 0.0}
    rs = [t.r_multiple for t in trades]
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r < 0]
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    net_r = sum(rs)

    # equity curve in R -> max drawdown
    eq = peak = mdd = 0.0
    for r in rs:
        eq += r
        peak = max(peak, eq)
        mdd = min(mdd, eq - peak)

    mean = net_r / n
    sd = math.sqrt(sum((r - mean) ** 2 for r in rs) / n) if n > 1 else 0.0
    downside = [r for r in rs if r < 0]
    dd_sd = math.sqrt(sum(r * r for r in downside) / n) if downside else 0.0
    win_streak, loss_streak = _streaks(rs)

    return {
        "trades": n,
        "win_rate": len(wins) / n * 100,
        "avg_win_r": (gross_win / len(wins)) if wins else 0.0,
        "avg_loss_r": (-gross_loss / len(losses)) if losses else 0.0,
        "expectancy_r": mean,                       # <-- the headline
        "net_r": net_r,
        "profit_factor": (gross_win / gross_loss) if gross_loss else float("inf"),
        "max_dd_r": mdd,
        "return_dd": (net_r / abs(mdd)) if mdd else float("inf"),
        "sharpe": (mean / sd) if sd else 0.0,       # per-trade Sharpe
        "sortino": (mean / dd_sd) if dd_sd else 0.0,
        "max_win_streak": win_streak,
        "max_loss_streak": loss_streak,
        "avg_bars_held": sum(t.bars_held for t in trades) / n,
        "avg_mae_pips": sum(t.mae_pips for t in trades) / n,
        "avg_mfe_pips": sum(t.mfe_pips for t in trades) / n,
    }


def by_reason(trades: List[Trade]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for t in trades:
        out[t.reason] = out.get(t.reason, 0) + 1
    return out


def fmt(m: Dict[str, float]) -> str:
    if not m.get("trades"):
        return "no trades"
    pf = m["profit_factor"]
    pf_s = "inf" if pf == float("inf") else f"{pf:.2f}"
    return (f"n={m['trades']:>4}  exp={m['expectancy_r']:+.3f}R  PF={pf_s:>5}  "
            f"win={m['win_rate']:4.1f}%  netR={m['net_r']:+6.1f}  "
            f"maxDD={m['max_dd_r']:+5.1f}R  Sharpe={m['sharpe']:+.2f}  "
            f"lossStk={m['max_loss_streak']}")
