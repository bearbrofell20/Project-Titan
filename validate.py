"""Validation harness — the part that keeps us honest.

Runs a strategy across pairs on cached history, then evaluates it the way a
professional would before risking money:

* **In-sample / out-of-sample / holdout** — a chronological 60/20/20 split. A
  strategy that only works in-sample is overfit.
* **Walk-forward** — rolling consecutive windows; we want positive expectancy in
  *most* windows, not one lucky stretch.
* **Parameter sensitivity** — sweep a *range* of each parameter; a strategy that
  only works at one exact value is fragile and rejected.

Everything is measured in R and pooled across pairs (trades sorted by entry
time) so the equity curve and drawdowns are portfolio-level.
"""

from __future__ import annotations

from typing import Callable, Dict, List, Optional

import bt
import data
import fast
import metrics
import oanda_trader as ot
from oanda_trader import STRATEGIES, Config, gate_signal

MAJORS = ["EUR_USD", "GBP_USD", "USD_JPY", "USD_CHF", "AUD_USD", "USD_CAD"]


def precompute(strategy: str, candles, trend_filter: bool = True, **kw):
    """Fast O(n) per-bar signal array for a strategy family."""
    if strategy == "ema_trend":
        return fast.ema_cross_signals(candles, Config.TREND_FAST, Config.TREND_SLOW)
    if strategy == "breakout":
        return fast.donchian_breakout_signals(candles, kw.get("lookback", 20))
    if strategy == "meanrev":
        return fast.bollinger_reversion_signals(candles, kw.get("period", 20), kw.get("k", 2.0))
    if strategy == "orb":
        return fast.opening_range_breakout_signals(
            candles, kw.get("open_hour", 7), kw.get("range_bars", 4),
            kw.get("window_end_hour", 11))
    raise ValueError(f"no fast precompute for {strategy!r}")


def make_sig(strategy: str, trend_filter: bool = True):
    """Build a signal function for `strategy`, applying the same-chart trend
    gate exactly as the live bot's gate_signal does."""
    det = STRATEGIES[strategy]

    def factory(inst):
        def sig_fn(w):
            Config.TREND_FILTER = trend_filter
            Config.HTF_FILTER = False
            s = det.get_signal(w, inst)
            return gate_signal(s, w, inst)
        return sig_fn
    return factory


def run(strategy: str, exits: bt.ExitConfig, costs: bt.Costs = bt.Costs(),
        gates: bt.Gates = bt.Gates(), pairs: Optional[List[str]] = None,
        gran: str = "M5", days: int = 120, trend_filter: bool = True, **params) -> Dict:
    """Run across pairs; return pooled trades (sorted by entry time) + per-pair."""
    pairs = pairs or MAJORS
    need_adx = gates.min_adx is not None
    need_atr = bool(exits.atr_mult_stop or exits.atr_mult_target or exits.trail_atr_mult)
    pooled: List[bt.Trade] = []
    per_pair, skips = {}, {}
    for inst in pairs:
        candles = data.load_history(inst, gran, days=days)
        signals = precompute(strategy, candles, trend_filter=trend_filter, **params)
        adx_arr = fast.adx_series(candles, gates.adx_period) if need_adx else None
        atr_arr = fast.atr_series(candles, exits.atr_period) if need_atr else None
        res = bt.simulate(candles, None, ot.pip_size(inst),
                          exits=exits, costs=costs, gates=gates,
                          signals=signals, adx_series=adx_arr, atr_series=atr_arr)
        per_pair[inst] = res["trades"]
        pooled.extend(res["trades"])
        for k, v in res["skips"].items():
            skips[k] = skips.get(k, 0) + v
    pooled.sort(key=lambda t: t.entry_time)
    return {"pooled": pooled, "per_pair": per_pair, "skips": skips}


def split_chrono(trades: List[bt.Trade], fracs=(0.6, 0.2, 0.2)):
    """Partition pooled trades chronologically by entry time."""
    if not trades:
        return {"IS": [], "OOS": [], "HOLDOUT": []}
    t0, t1 = trades[0].entry_time, trades[-1].entry_time
    span = max(1, t1 - t0)
    b1 = t0 + span * fracs[0]
    b2 = t0 + span * (fracs[0] + fracs[1])
    IS = [t for t in trades if t.entry_time < b1]
    OOS = [t for t in trades if b1 <= t.entry_time < b2]
    HO = [t for t in trades if t.entry_time >= b2]
    return {"IS": IS, "OOS": OOS, "HOLDOUT": HO}


def walk_forward(trades: List[bt.Trade], windows: int = 6):
    """Split pooled trades into `windows` equal time slices; summarize each."""
    if not trades:
        return []
    t0, t1 = trades[0].entry_time, trades[-1].entry_time
    span = max(1, t1 - t0)
    out = []
    for k in range(windows):
        lo = t0 + span * k / windows
        hi = t0 + span * (k + 1) / windows
        chunk = [t for t in trades if lo <= t.entry_time < hi]
        out.append(metrics.summarize(chunk))
    return out
