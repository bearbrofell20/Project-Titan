"""Event-driven backtester with realistic costs and strict no-look-ahead.

Rules enforced:
  * A signal decided at the CLOSE of bar i is executed at the OPEN of bar i+1.
  * Fills pay the spread (from real bid/ask) + slippage; long buys the ask side,
    sells the bid side (short is the mirror).
  * Within a bar, if both stop and target could be touched, the STOP is assumed
    hit first (worst-case, no intrabar optimism).
  * Position sizing risks exactly `risk_per_trade` of current equity at the stop.
  * One position at a time; day-loss / drawdown / streak / spread circuit breakers.
  * Positions are flattened at/after the overnight UTC cutoff (day-trading).
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass
from typing import List, Optional

from config import CostConfig, RiskConfig, StrategyConfig, PIP
from data_manager import Bar
from strategy import Signals

log = logging.getLogger("bt")


@dataclass
class Trade:
    direction: int
    entry_ts: int
    exit_ts: int
    entry_px: float
    exit_px: float
    units: float
    risk_usd: float
    pnl_usd: float
    r_multiple: float
    bars_held: int
    mae_r: float
    mfe_r: float
    reason: str
    entry_hour: int


def _session(hour: int) -> str:
    # UTC sessions (approx): Asian 0-7, London 7-12, Overlap 12-16, NY 16-21
    if 7 <= hour < 12:
        return "london"
    if 12 <= hour < 16:
        return "overlap"
    if 16 <= hour < 21:
        return "newyork"
    return "asian"


def simulate(m15: List[Bar], sig: Signals, scfg: StrategyConfig,
             rcfg: RiskConfig, ccfg: CostConfig,
             apply_circuit_breakers: bool = False) -> List[Trade]:
    """Set apply_circuit_breakers=False (default) to measure the strategy's raw
    edge; the daily-loss / drawdown / consecutive-loss halts are a live-safety
    overlay that would suppress trades and bias the expectancy estimate. They are
    tested as a separate question (Part 15), not baked into edge measurement."""
    trades: List[Trade] = []
    equity = rcfg.starting_equity
    peak_equity = equity
    consec_losses = 0
    halted = False  # drawdown / streak circuit breaker (no new entries)

    day_key: Optional[int] = None
    day_start_equity = equity

    i = 0
    n = len(m15)
    pos = None  # open position dict

    def spread_price(bar: Bar) -> float:
        return max(0.0, (bar.ask_c - bar.bid_c)) * ccfg.spread_mult

    def slip() -> float:
        return ccfg.slippage_pips * PIP

    while i < n:
        bar = m15[i]

        # ---- day boundary bookkeeping (daily-loss reset) ----
        d = dt.datetime.utcfromtimestamp(bar.ts)
        dk = d.toordinal()
        if dk != day_key:
            day_key = dk
            day_start_equity = equity

        # ---------------- manage an open position ----------------
        if pos is not None:
            hit = None
            exit_px = None
            # worst-case ordering: check stop against this bar's extreme first
            if pos["dir"] == 1:
                # update MAE/MFE
                pos["mae"] = min(pos["mae"], bar.l - pos["entry_mid"])
                pos["mfe"] = max(pos["mfe"], bar.h - pos["entry_mid"])
                if bar.l <= pos["stop"]:
                    hit, exit_mid = "stop", pos["stop"]
                elif pos["target"] and bar.h >= pos["target"]:
                    hit, exit_mid = "target", pos["target"]
            else:
                pos["mae"] = min(pos["mae"], pos["entry_mid"] - bar.h)
                pos["mfe"] = max(pos["mfe"], pos["entry_mid"] - bar.l)
                if bar.h >= pos["stop"]:
                    hit, exit_mid = "stop", pos["stop"]
                elif pos["target"] and bar.l <= pos["target"]:
                    hit, exit_mid = "target", pos["target"]

            # overnight cutoff / time-stop -> exit at bar close
            cutoff = scfg.overnight_cutoff_hour_utc
            if hit is None and cutoff is not None and bar.hour_utc >= cutoff:
                hit, exit_mid = "overnight", bar.c
            if hit is None and scfg.max_hold_bars and pos["bars"] >= scfg.max_hold_bars:
                hit, exit_mid = "time", bar.c

            if hit is not None:
                sp = spread_price(bar) / 2.0
                if pos["dir"] == 1:
                    exit_px = exit_mid - sp - slip()      # sell the bid
                else:
                    exit_px = exit_mid + sp + slip()      # buy the ask
                pnl = pos["units"] * (exit_px - pos["entry_px"]) * pos["dir"]
                equity += pnl
                peak_equity = max(peak_equity, equity)
                r = pnl / pos["risk_usd"] if pos["risk_usd"] > 0 else 0.0
                trades.append(Trade(
                    direction=pos["dir"], entry_ts=pos["entry_ts"], exit_ts=bar.ts,
                    entry_px=pos["entry_px"], exit_px=exit_px, units=pos["units"],
                    risk_usd=pos["risk_usd"], pnl_usd=pnl, r_multiple=r,
                    bars_held=pos["bars"], reason=hit,
                    mae_r=(pos["mae"] / pos["risk_price"]) if pos["risk_price"] else 0.0,
                    mfe_r=(pos["mfe"] / pos["risk_price"]) if pos["risk_price"] else 0.0,
                    entry_hour=pos["entry_hour"]))
                consec_losses = consec_losses + 1 if r <= 0 else 0
                if apply_circuit_breakers:
                    if consec_losses >= rcfg.max_consecutive_losses:
                        halted = True
                    if (peak_equity - equity) / peak_equity >= rcfg.max_drawdown:
                        halted = True
                pos = None
            else:
                # trailing stop (ATR-based), favorable direction only
                if scfg.trail_atr_mult and sig.atr[i]:
                    dist = scfg.trail_atr_mult * sig.atr[i]
                    if pos["dir"] == 1:
                        pos["stop"] = max(pos["stop"], bar.c - dist)
                    else:
                        pos["stop"] = min(pos["stop"], bar.c + dist)
                # break-even bump
                if scfg.breakeven_at_r and not pos["be_done"]:
                    move = (bar.c - pos["entry_mid"]) * pos["dir"]
                    if move >= scfg.breakeven_at_r * pos["risk_price"]:
                        pos["stop"] = (pos["entry_mid"] if pos["dir"] == 1 else pos["entry_mid"])
                        pos["be_done"] = True
                pos["bars"] += 1
                i += 1
                continue

        # ---------------- consider a new entry ----------------
        # signal was decided at close of bar i-1 -> act at open of bar i
        if pos is None and i >= 1 and not halted:
            s = sig.direction[i - 1]
            atr_prev = sig.atr[i - 1]
            day_dd = (day_start_equity - equity) / day_start_equity if day_start_equity else 0.0
            spread_pips_now = (bar.ask_c - bar.bid_c) / PIP
            allowed_session = (not scfg.sessions_utc) or (bar.hour_utc in scfg.sessions_utc)
            cutoff = scfg.overnight_cutoff_hour_utc
            too_late = cutoff is not None and bar.hour_utc >= cutoff
            day_ok = (not apply_circuit_breakers) or (day_dd < rcfg.max_daily_loss)
            if (s != 0 and atr_prev and atr_prev > 0
                    and day_ok
                    and spread_pips_now <= rcfg.max_spread_pips
                    and allowed_session and not too_late):
                sp = spread_price(bar) / 2.0
                entry_mid = bar.o
                if s == 1:
                    entry_px = entry_mid + sp + slip()
                else:
                    entry_px = entry_mid - sp - slip()
                risk_price = scfg.stop_atr_mult * atr_prev
                risk_usd = equity * rcfg.risk_per_trade
                units = risk_usd / risk_price
                stop = entry_mid - s * risk_price
                target = (entry_mid + s * scfg.target_r * risk_price) if scfg.target_r else 0.0
                pos = {"dir": s, "entry_ts": bar.ts, "entry_px": entry_px,
                       "entry_mid": entry_mid, "units": units, "risk_usd": risk_usd,
                       "risk_price": risk_price, "stop": stop, "target": target,
                       "bars": 0, "mae": 0.0, "mfe": 0.0, "be_done": False,
                       "entry_hour": bar.hour_utc}
        i += 1

    return trades
