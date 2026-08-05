#!/usr/bin/env python3
"""
Backtester — test every strategy over historical OANDA candles in seconds.

    python backtest.py                 # compare ALL strategies (default 1000 M5 bars)
    python backtest.py all 1500        # ALL strategies over 1500 bars (~5 days)
    python backtest.py ema_pullback    # just one strategy, more detail

For each strategy it replays the candles bar by bar, takes the same entry signal
the live bot would, then walks forward using each later bar's high/low to see
whether the take-profit or stop-loss is hit first (SL assumed first if a bar
touches both — conservative). Results are pip-based (venue-neutral) plus a dollar
estimate using your fixed-risk model, aggregated across all monitored pairs.

This is how you compare strategies without waiting a week each. It is a
simplification — no spread, slippage, or financing — so treat it as a relative
ranking, not a profit promise. Confirm the winner on the live demo.
"""

from __future__ import annotations

import sys

import oanda_trader as ot
from oanda_trader import Config, OandaClient, STRATEGIES, completed_candles, pip_size


def _minutes_per_bar(granularity):
    """Approximate minutes per candle for an OANDA granularity code."""
    unit = {"S": 1 / 60, "M": 1, "H": 60, "D": 1440, "W": 10080}[granularity[0]]
    num = granularity[1:]
    return unit * (int(num) if num else 1)


def simulate(candles, signal_fn, sl_pips, tp_pips, pip_sz, warmup=25):
    """Replay candles through a signal function; return a list of closed trades.

    Only one position at a time per series: after an entry we jump forward to the
    bar where it closed before looking for the next signal.
    """
    trades = []
    n = len(candles)
    i = max(warmup, 1)
    while i < n:
        sig = signal_fn(candles[: i + 1])
        if sig not in ("BUY", "SELL"):
            i += 1
            continue

        entry = float(candles[i]["mid"]["c"])
        if sig == "BUY":
            tp, sl = entry + tp_pips * pip_sz, entry - sl_pips * pip_sz
        else:
            tp, sl = entry - tp_pips * pip_sz, entry + sl_pips * pip_sz

        outcome = None
        j = i + 1
        while j < n:
            hi = float(candles[j]["mid"]["h"])
            lo = float(candles[j]["mid"]["l"])
            if sig == "BUY":
                if lo <= sl:          # SL checked first (conservative)
                    outcome = -sl_pips
                    break
                if hi >= tp:
                    outcome = tp_pips
                    break
            else:
                if hi >= sl:
                    outcome = -sl_pips
                    break
                if lo <= tp:
                    outcome = tp_pips
                    break
            j += 1

        if outcome is None:
            break  # trade still open at the end of data — stop here
        trades.append({"dir": sig, "entry": entry, "pips": outcome, "exit": j})
        i = j + 1
    return trades


def summarize(trades, risk_usd, sl_pips, tp_pips):
    wins = [t for t in trades if t["pips"] > 0]
    losses = [t for t in trades if t["pips"] < 0]
    net_pips = sum(t["pips"] for t in trades)
    gp = sum(t["pips"] for t in wins)
    gl = sum(t["pips"] for t in losses)
    pf = (gp / abs(gl)) if gl else (float("inf") if gp else 0.0)
    win_rate = (len(wins) / len(trades) * 100) if trades else 0.0

    # Equity curve (in pips) -> max drawdown.
    eq = peak = mdd = 0.0
    for t in trades:
        eq += t["pips"]
        peak = max(peak, eq)
        mdd = min(mdd, eq - peak)

    # Dollar estimate under fixed-risk sizing: a loss = -risk, a win = risk*(TP/SL).
    win_r = tp_pips / sl_pips
    est_usd = len(wins) * risk_usd * win_r - len(losses) * risk_usd
    return {
        "trades": len(trades), "wins": len(wins), "losses": len(losses),
        "win_rate": win_rate, "net_pips": net_pips, "profit_factor": pf,
        "max_dd_pips": mdd, "est_usd": est_usd,
    }


def _pf(x):
    return "  ∞ " if x == float("inf") else f"{x:5.2f}"


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    count = int(sys.argv[2]) if len(sys.argv) > 2 else 1000

    if which != "all" and which not in STRATEGIES:
        print(f"Unknown strategy {which!r}. Choices: all, {', '.join(STRATEGIES)}")
        raise SystemExit(1)
    selected = list(STRATEGIES) if which == "all" else [which]

    client = OandaClient(ot._load_api_token())

    # Fetch candle history once per instrument (shared across strategies).
    print(f"Fetching {count} {Config.TIMEFRAME} candles for {len(Config.INSTRUMENTS)} pairs...")
    history = {}
    for inst in Config.INSTRUMENTS:
        raw = client.get_candles(inst, granularity=Config.TIMEFRAME, count=count)
        history[inst] = completed_candles(raw)

    results = {}
    for name in selected:
        detector = STRATEGIES[name]
        all_trades = []
        for inst in Config.INSTRUMENTS:
            candles = history[inst]
            if len(candles) < 30:
                continue
            trades = simulate(
                candles,
                lambda w, _i=inst: detector.get_signal(w, _i),
                Config.STOP_LOSS_PIPS, Config.TAKE_PROFIT_PIPS, pip_size(inst),
            )
            all_trades.extend(trades)
        results[name] = summarize(
            all_trades, Config.RISK_PER_TRADE, Config.STOP_LOSS_PIPS, Config.TAKE_PROFIT_PIPS
        )

    span_days = count * _minutes_per_bar(Config.TIMEFRAME) / 60 / 24
    print("=" * 74)
    print(f" BACKTEST · {len(Config.INSTRUMENTS)} pairs · ~{span_days:.1f} days "
          f"· SL {Config.STOP_LOSS_PIPS}/TP {Config.TAKE_PROFIT_PIPS} pips "
          f"· ${Config.RISK_PER_TRADE}/trade")
    print("=" * 74)
    print(f" {'strategy':<14}{'trades':>7}{'win%':>7}{'net pips':>10}"
          f"{'PF':>7}{'max DD':>9}{'est $':>10}")
    print("-" * 74)
    for name in sorted(results, key=lambda k: results[k]["est_usd"], reverse=True):
        s = results[name]
        print(f" {name:<14}{s['trades']:>7}{s['win_rate']:>6.1f}%{s['net_pips']:>10.0f}"
              f"{_pf(s['profit_factor']):>7}{s['max_dd_pips']:>9.0f}{s['est_usd']:>10,.0f}")
    print("=" * 74)
    print(" Pip-based, no spread/slippage/financing — a relative ranking, not a")
    print(" profit promise. Confirm the winner on the live demo before real money.")


if __name__ == "__main__":
    main()
