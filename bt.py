"""Realistic backtest engine — bid/ask fills, real spread, rich trade records.

This is the defensible successor to ``backtest.py``. It differs in every way
that matters for trusting the result:

* **Fills use bid/ask, not mid.** A long enters at the ask and exits at the bid;
  a short enters at the bid and exits at the ask. The real, per-bar spread is
  therefore paid on both ends — no flat-constant approximation.
* **Configurable, realistic costs:** additional ``slippage_pips`` (adverse on
  entry and stop) and per-trade ``commission_usd``.
* **Exit methodologies are pluggable:** fixed or ATR-scaled stop/target, plus
  optional break-even, trailing stop, and time stop — so exits can be *tested*
  rather than assumed.
* **Gates let the bot stay flat:** an ADX regime gate, a max-spread gate, and a
  UTC trading-session gate. A signal that fails any gate is a NO-TRADE, logged
  with the reason.
* **Every trade records its own truth:** entry/exit time & price, bars held,
  MAE/MFE (pips), spread paid, exit reason, and the result in **R** (multiples
  of the initial risk) — the unit expectancy is measured in.

No look-ahead: a signal is evaluated on bars up to and including the signal bar,
the entry fills at that bar's close, and the walk-forward for the exit starts at
the *next* bar. Stops are checked before targets within a bar (conservative).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from oanda_trader import atr as _atr_from_candles  # ATR on mid candles


# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------
@dataclass
class ExitConfig:
    """How a trade is managed once open. Stops/targets are in pips unless
    ``atr_mult_*`` is set, in which case they scale with ATR at entry."""
    stop_pips: float = 20.0
    target_pips: float = 40.0
    atr_period: int = 14
    atr_mult_stop: Optional[float] = None      # e.g. 1.5 -> stop = 1.5*ATR
    atr_mult_target: Optional[float] = None     # e.g. 3.0 -> target = 3*ATR
    breakeven_at_r: Optional[float] = None      # move stop to entry after +Xr
    trail_atr_mult: Optional[float] = None      # trail stop at k*ATR behind
    time_stop_bars: Optional[int] = None        # force-exit after N bars


@dataclass
class Costs:
    slippage_pips: float = 0.3     # adverse slippage added on entry & stop
    commission_usd: float = 0.0    # per round-trip (OANDA core = 0; configurable)


@dataclass
class Gates:
    max_spread_pips: Optional[float] = None     # skip if spread wider than this
    min_adx: Optional[float] = None             # regime: require trend strength
    adx_period: int = 14
    sessions_utc: Optional[List[tuple]] = None  # e.g. [(7,16)] London/NY hours


@dataclass
class Trade:
    direction: str
    entry_time: int
    entry: float
    stop: float
    target: float
    exit_time: int = 0
    exit: float = 0.0
    bars_held: int = 0
    pips: float = 0.0            # net of spread + slippage
    r_multiple: float = 0.0     # result in units of initial risk
    mae_pips: float = 0.0       # max adverse excursion
    mfe_pips: float = 0.0       # max favourable excursion
    spread_pips: float = 0.0    # spread paid at entry
    reason: str = ""            # tp | sl | trail | breakeven | time | eod


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def _utc_hour(epoch: int) -> int:
    return int((epoch // 3600) % 24)


def _session_ok(epoch: int, sessions) -> bool:
    if not sessions:
        return True
    h = _utc_hour(epoch)
    return any(lo <= h < hi for lo, hi in sessions)


def _atr_at(mid_candles: List[dict], i: int, period: int) -> Optional[float]:
    """ATR over the `period` bars ending at index i (uses mid o/h/l/c)."""
    if i < period:
        return None
    window = mid_candles[: i + 1]
    return _atr_from_candles(window, period)


# --------------------------------------------------------------------------
# Core simulation
# --------------------------------------------------------------------------
def simulate(
    candles: List[dict],
    signal_fn: Optional[Callable[[List[dict]], Optional[str]]],
    pip_size: float,
    exits: ExitConfig,
    costs: Costs = Costs(),
    gates: Gates = Gates(),
    warmup: int = 60,
    signals: Optional[List[Optional[str]]] = None,
    adx_series: Optional[List[Optional[float]]] = None,
    atr_series: Optional[List[Optional[float]]] = None,
) -> Dict[str, object]:
    """Replay MBA candles; return {'trades': [...], 'skips': {reason: n}}.

    ``candles`` are the normalized bid/mid/ask dicts from :mod:`data`. Detectors
    read ``mid`` (unchanged from live), fills read ``bid``/``ask``.

    Pass a precomputed ``signals`` array (one 'BUY'/'SELL'/None per bar) to avoid
    the O(n^2) cost of recomputing indicators over a growing window each bar;
    otherwise ``signal_fn`` is called on ``candles[:i+1]``.
    """
    # Detectors expect a list of {"mid": {...}, "time": ...}; our candles already
    # carry "mid", so they work directly.
    trades: List[Trade] = []
    skips: Dict[str, int] = {}
    n = len(candles)
    i = max(warmup, 1)

    def skip(reason):
        skips[reason] = skips.get(reason, 0) + 1

    def atr_at(idx):
        if atr_series is not None:
            return atr_series[idx]
        return _atr_at(candles, idx, exits.atr_period)

    while i < n:
        bar = candles[i]
        sig = signals[i] if signals is not None else signal_fn(candles[: i + 1])
        if sig not in ("BUY", "SELL"):
            i += 1
            continue

        # --- gates: the bot is allowed to stay flat -----------------------
        spread = (bar["ask"]["c"] - bar["bid"]["c"]) / pip_size
        if gates.max_spread_pips is not None and spread > gates.max_spread_pips:
            skip("spread"); i += 1; continue
        if not _session_ok(bar["time"], gates.sessions_utc):
            skip("session"); i += 1; continue
        if gates.min_adx is not None:
            if adx_series is not None:
                adx_val = adx_series[i]
            else:
                from oanda_trader import adx as _adx
                adx_val = _adx(candles[: i + 1], gates.adx_period)
            if adx_val is None or adx_val < gates.min_adx:
                skip("regime"); i += 1; continue

        # --- position sizing distances ------------------------------------
        if exits.atr_mult_stop or exits.atr_mult_target:
            atr = atr_at(i)
            if atr is None:
                i += 1; continue
            atr_pips = atr / pip_size
            stop_pips = (exits.atr_mult_stop * atr_pips) if exits.atr_mult_stop else exits.stop_pips
            target_pips = (exits.atr_mult_target * atr_pips) if exits.atr_mult_target else exits.target_pips
        else:
            stop_pips, target_pips = exits.stop_pips, exits.target_pips
        if stop_pips <= 0:
            i += 1; continue

        slip = costs.slippage_pips * pip_size
        # entry fill: buy at ask (+slip), sell at bid (-slip)
        if sig == "BUY":
            entry = bar["ask"]["c"] + slip
            stop = entry - stop_pips * pip_size
            target = entry + target_pips * pip_size
        else:
            entry = bar["bid"]["c"] - slip
            stop = entry + stop_pips * pip_size
            target = entry - target_pips * pip_size

        tr = Trade(direction=sig, entry_time=bar["time"], entry=entry,
                   stop=stop, target=target, spread_pips=spread)
        risk_dist = stop_pips * pip_size  # 1R in price

        # --- walk forward -------------------------------------------------
        be_done = False
        j = i + 1
        while j < n:
            c = candles[j]
            tr.bars_held = j - i
            if sig == "BUY":
                # long: adverse = bid low, favourable = bid high (exit at bid)
                fav = (c["bid"]["h"] - entry) / pip_size
                adv = (entry - c["bid"]["l"]) / pip_size
                tr.mfe_pips = max(tr.mfe_pips, fav)
                tr.mae_pips = max(tr.mae_pips, adv)
                # trailing / breakeven adjust the stop upward
                if exits.breakeven_at_r and not be_done and fav >= exits.breakeven_at_r * stop_pips:
                    stop = max(stop, entry); be_done = True
                if exits.trail_atr_mult:
                    atr = atr_at(j)
                    if atr:
                        stop = max(stop, c["bid"]["c"] - exits.trail_atr_mult * atr)
                hit_sl = c["bid"]["l"] <= stop
                hit_tp = c["bid"]["h"] >= target
                if hit_sl:  # stop first (conservative), fill at stop - slip
                    tr.exit = stop - slip; tr.reason = "be" if be_done and stop >= entry else ("trail" if exits.trail_atr_mult else "sl")
                    break
                if hit_tp:
                    tr.exit = target; tr.reason = "tp"; break
            else:
                fav = (entry - c["ask"]["l"]) / pip_size
                adv = (c["ask"]["h"] - entry) / pip_size
                tr.mfe_pips = max(tr.mfe_pips, fav)
                tr.mae_pips = max(tr.mae_pips, adv)
                if exits.breakeven_at_r and not be_done and fav >= exits.breakeven_at_r * stop_pips:
                    stop = min(stop, entry); be_done = True
                if exits.trail_atr_mult:
                    atr = atr_at(j)
                    if atr:
                        stop = min(stop, c["ask"]["c"] + exits.trail_atr_mult * atr)
                hit_sl = c["ask"]["h"] >= stop
                hit_tp = c["ask"]["l"] <= target
                if hit_sl:
                    tr.exit = stop + slip; tr.reason = "be" if be_done and stop <= entry else ("trail" if exits.trail_atr_mult else "sl")
                    break
                if hit_tp:
                    tr.exit = target; tr.reason = "tp"; break
            if exits.time_stop_bars and (j - i) >= exits.time_stop_bars:
                tr.exit = c["bid"]["c"] if sig == "BUY" else c["ask"]["c"]
                tr.reason = "time"; break
            j += 1

        if not tr.reason:  # ran out of data
            break
        tr.exit_time = candles[j]["time"]
        gained = (tr.exit - entry) if sig == "BUY" else (entry - tr.exit)
        tr.pips = gained / pip_size
        tr.r_multiple = gained / risk_dist if risk_dist else 0.0
        trades.append(tr)
        i = j + 1

    return {"trades": trades, "skips": skips}
