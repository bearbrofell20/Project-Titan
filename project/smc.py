"""SMC strategy: LIQUIDITY SWEEP -> MSS -> RETEST -> ENTRY (objective, causal).

State machine per direction (bullish shown; bearish mirrored):
  1. SWEEP    : bar sweeps the previous-day LOW and closes back above it.
  2. MSS      : within `mss_window` bars, a bullish structure break (BOS/CHOCH up)
                with displacement (body/ATR) >= `disp_min`.
  3. RETEST   : within `retest_window` bars after MSS, price trades back down to
                the broken level and closes back above it.
  4. ENTRY    : emit +1 (executed at next bar open by the backtester).

Ablation switches (`require_mss`, `require_retest`) let us measure each stage's
contribution instead of assuming the full stack is best.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

from config import StrategyConfig
from data_manager import Bar
import indicators as ind
from strategy import Signals
from structure import build_structure
from liquidity import prev_day_levels, sweeps


@dataclass
class SMCParams:
    swing_L: int = 2
    disp_min: float = 0.5
    mss_window: int = 8
    retest_window: int = 10
    require_mss: bool = True
    require_retest: bool = True


def build_smc_signals(bars: List[Bar], p: SMCParams, atr_period: int = 14) -> Signals:
    n = len(bars)
    atr = ind.atr([b.h for b in bars], [b.l for b in bars], [b.c for b in bars], atr_period)
    st = build_structure(bars, L=p.swing_L, atr_period=atr_period)
    lv = prev_day_levels(bars)
    sw = sweeps(bars, lv)

    direction = [0] * n
    stop_px: List = [None] * n     # structure stop = the swept extreme
    pend = []  # each: {"dir","stage","mss_deadline","retest_deadline","ref","stop"}

    def enter(i, d, stop):
        if direction[i] == 0:
            direction[i] = d
            stop_px[i] = stop

    for i in range(n):
        # 1) new sweep arms a setup; the swept wick extreme is the protective stop
        if sw[i] == 1:
            pend.append({"dir": 1, "stage": "swept", "mss_deadline": i + p.mss_window,
                         "retest_deadline": None, "ref": None, "stop": bars[i].l})
        elif sw[i] == -1:
            pend.append({"dir": -1, "stage": "swept", "mss_deadline": i + p.mss_window,
                         "retest_deadline": None, "ref": None, "stop": bars[i].h})

        ev = st.events[i]
        still = []
        for s in pend:
            d = s["dir"]
            if not p.require_mss:          # SWEEP-only: enter on the sweep bar
                enter(i, d, s["stop"])
                continue
            if s["stage"] == "swept":
                if i > s["mss_deadline"]:
                    continue
                if ev is not None and ev.direction == d and ev.displacement >= p.disp_min:
                    if not p.require_retest:
                        enter(i, d, s["stop"]); continue
                    s["stage"] = "mss"; s["ref"] = ev.ref_price
                    s["retest_deadline"] = i + p.retest_window
                    still.append(s)
                else:
                    still.append(s)
            elif s["stage"] == "mss":
                if i > s["retest_deadline"]:
                    continue
                ref = s["ref"]
                if d == 1 and bars[i].l <= ref and bars[i].c > ref:
                    enter(i, d, s["stop"]); continue
                if d == -1 and bars[i].h >= ref and bars[i].c < ref:
                    enter(i, d, s["stop"]); continue
                still.append(s)
        pend = still

    return Signals(direction=direction, atr=atr, ema=[None] * n,
                   h4_ema_at=[None] * n, h4_close_at=[None] * n,
                   stop_px=stop_px, target_px=None)
