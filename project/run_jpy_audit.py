"""Hostile audit of the JPY-cross trend edge, using the strict harness.

Independent re-test of the one config in this project that showed out-of-sample
signal: an EMA 20/60 trend-follow on AUD_JPY + EUR_JPY (H1). To avoid merely
reproducing the discovery, exits here are ATR-based (not the fixed 30/75 pips it
was found with) — if the edge is real it should survive a different exit too.

Data caveat (loud): these H1 candles are Yahoo mid with a SYNTHETIC constant
spread, not real bid/ask. A positive result here is corroboration, not proof; the
real test is the live paper bot on OANDA's real spreads.
"""

from __future__ import annotations

import dataclasses as dc
import logging
import os

from config import Config, StrategyConfig
import data_manager as dm
import metrics
import monte_carlo
from strategy import build_signals
from backtester import simulate

logging.basicConfig(level=logging.INFO, format="%(message)s")
PAIRS = ["AUD_JPY", "EUR_JPY"]
DATA_DIR = os.getenv("DATA_DIR", "../market_data")

# Pre-registered single config (matches the discovered edge; ATR exits).
STRAT = dict(entry_style="ema_trend", fast_ema=20, slow_ema=60,
             atr_period=14, stop_atr_mult=1.5, trail_atr_mult=0.0,
             target_r=2.5, overnight_cutoff_hour_utc=None, sessions_utc=[])


def pooled_trades(base: Config):
    allt = []
    for p in PAIRS:
        candles = dm.load_candles(f"{DATA_DIR}/{p}_H1.json")
        bars = dm.to_bars(candles, "H1")
        scfg = dc.replace(base.strategy, instrument=p, **STRAT)
        sig = build_signals(bars, [], scfg)
        t = simulate(bars, sig, scfg, base.risk, base.cost)
        allt.extend(t)
    allt.sort(key=lambda x: x.entry_ts)
    return allt


def split(trades, fracs=(0.6, 0.2, 0.2)):
    if not trades:
        return {}
    t0, t1 = trades[0].entry_ts, trades[-1].entry_ts
    span = max(1, t1 - t0)
    b1, b2 = t0 + span * fracs[0], t0 + span * (fracs[0] + fracs[1])
    return {"IS": [t for t in trades if t.entry_ts < b1],
            "VALID": [t for t in trades if b1 <= t.entry_ts < b2],
            "OOS": [t for t in trades if t.entry_ts >= b2]}


def walk(trades, w=6):
    if not trades:
        return []
    t0, t1 = trades[0].entry_ts, trades[-1].entry_ts
    span = max(1, t1 - t0)
    out = []
    for k in range(w):
        lo, hi = t0 + span * k / w, t0 + span * (k + 1) / w
        out.append(metrics.summarize([t for t in trades if lo <= t.entry_ts < hi]))
    return out


def main():
    base = Config()
    trades = pooled_trades(base)
    print(f"=== JPY-cross trend audit: ema_trend 20/60, ATR stop 1.5x, 2.5R target, H1 ===")
    print(f"pairs={PAIRS}  pooled trades={len(trades)}\n")
    sl = split(trades)
    print("ALL     ", metrics.fmt(metrics.summarize(trades)))
    for k in ("IS", "VALID", "OOS"):
        print(f"{k:8s}", metrics.fmt(metrics.summarize(sl[k])))
    print("\nwalk-forward (6 windows):")
    pos = 0
    for i, w in enumerate(walk(trades, 6), 1):
        pos += 1 if w.get("expectancy_r", 0) > 0 else 0
        print(f"  w{i} {metrics.fmt(w)}")
    print(f"  -> {pos}/6 windows positive")
    print("\ncost stress:")
    for mult, slp in [(1.0, 0.3), (1.5, 0.5), (2.0, 1.0)]:
        c = dc.replace(base, cost=dc.replace(base.cost, spread_mult=mult, slippage_pips=slp))
        t = pooled_trades(c)
        print(f"  spread x{mult}, slip {slp}p: {metrics.fmt(metrics.summarize(t))}")
    print("\nMonte Carlo:", monte_carlo.run(trades))

    oos = metrics.summarize(sl["OOS"])
    allm = metrics.summarize(trades)
    print("\n================= VERDICT =================")
    robust = (oos["expectancy_r"] > 0 and allm["profit_factor"] >= 1.10 and pos >= 4)
    if robust:
        print("PROMISING — positive out-of-sample and holds across windows on this")
        print("(synthetic-spread) data. Confirm on live real-bid/ask paper trading.")
    else:
        print("DID NOT hold up under the strict audit — treat as NOT validated.")


if __name__ == "__main__":
    main()
