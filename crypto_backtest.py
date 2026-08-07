"""Calibration backtest for the Kalshi crypto fair-value model.

The trading premise for the KXBTC15M markets is: our driftless-lognormal model
gives the *true* probability that BTC finishes >= a strike, and we profit when the
market price disagrees with it. That premise only holds if the model's
probabilities are actually calibrated — so this measures exactly that against real
BTC history, with no look-ahead:

* reconstruct every 15-minute window (strike = price at the open),
* at several points inside each window (12/8/4 min left) compute the model's
  probability from the spot then and realized vol over the *prior* 90 minutes,
* compare the predicted probability to the realized settlement outcome.

Reported: Brier score, Brier **skill** vs always predicting the base rate
(positive = real skill), and a reliability table (predicted bucket -> realized
frequency; a calibrated model sits on the diagonal).

Data comes from :func:`load_btc_1m` (cached Coinbase 1-minute closes).
"""

from __future__ import annotations

import json
import math
import statistics
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from kalshi_trader.crypto_model import MINUTES_PER_YEAR, fair_prob_ge

BTC_CACHE = Path("market_data/BTC_1m.json")


def load_btc_1m() -> Dict[int, float]:
    """Cached 1-minute BTC closes as {epoch: close}."""
    series = json.loads(BTC_CACHE.read_text())
    return {int(t): float(c) for t, c in series}


def realized_vol_annual(close: Dict[int, float], t_now: int, lookback_min: int = 90) -> Optional[float]:
    """Annualized vol from 1-min log returns over the prior `lookback_min`
    minutes ending at t_now (uses only past data — no look-ahead)."""
    cs = [close[t] for t in range(t_now - lookback_min * 60, t_now + 1, 60) if t in close]
    if len(cs) < 10:
        return None
    rets = [math.log(cs[i] / cs[i - 1]) for i in range(1, len(cs)) if cs[i - 1] > 0]
    if len(rets) < 5:
        return None
    return statistics.pstdev(rets) * math.sqrt(MINUTES_PER_YEAR)


def reconstruct(close: Dict[int, float], eval_points=(3, 7, 11)) -> List[Tuple[float, int]]:
    """Return [(model_prob, outcome)] over all reconstructable 15-min windows."""
    if not close:
        return []
    mins = sorted(close)
    preds: List[Tuple[float, int]] = []
    start = mins[0] - (mins[0] % 900) + 900
    for t0 in range(start, mins[-1] - 900, 900):
        if t0 not in close or (t0 + 900) not in close:
            continue
        strike = close[t0]
        outcome = 1 if close[t0 + 900] >= strike else 0
        for k in eval_points:
            te = t0 + k * 60
            if te not in close:
                continue
            vol = realized_vol_annual(close, te)
            if vol is None:
                continue
            p = fair_prob_ge(close[te], strike, 15 - k, vol)
            preds.append((p, outcome))
    return preds


def brier(preds: List[Tuple[float, int]]) -> float:
    return sum((p - o) ** 2 for p, o in preds) / len(preds) if preds else 0.0


def skill_score(preds: List[Tuple[float, int]]) -> float:
    """Brier skill vs always predicting the base rate. >0 means real skill."""
    if not preds:
        return 0.0
    base = sum(o for _, o in preds) / len(preds)
    bb = sum((base - o) ** 2 for _, o in preds) / len(preds)
    return 1 - brier(preds) / bb if bb else 0.0


def reliability(preds: List[Tuple[float, int]], bins: int = 10):
    """[(lo, hi, n, mean_pred, mean_actual)] per probability decile."""
    out = []
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        sub = [(p, o) for p, o in preds if lo <= p < hi or (b == bins - 1 and p == 1.0)]
        if sub:
            mp = sum(p for p, _ in sub) / len(sub)
            ma = sum(o for _, o in sub) / len(sub)
            out.append((lo, hi, len(sub), mp, ma))
    return out


def main():
    close = load_btc_1m()
    preds = reconstruct(close)
    n = len(preds)
    base = sum(o for _, o in preds) / n
    print(f"predictions={n}  base_rate={base:.3f}  brier={brier(preds):.4f}  "
          f"skill={skill_score(preds):+.4f}")
    print(f"  {'bucket':>9} {'n':>6} {'pred':>7} {'actual':>7}")
    for lo, hi, cnt, mp, ma in reliability(preds):
        flag = "  <- off" if abs(mp - ma) > 0.06 else ""
        print(f"  {int(lo*100):>3}-{int(hi*100):<3}% {cnt:>6} {mp:>7.3f} {ma:>7.3f}{flag}")


if __name__ == "__main__":
    main()
