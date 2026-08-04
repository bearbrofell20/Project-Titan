"""Offline tests for the backtest engine (no network)."""

import backtest


def _ohlc(o, h, l, c):
    return {"mid": {"o": str(o), "h": str(h), "l": str(l), "c": str(c)},
            "time": "0", "complete": True}


def test_simulate_take_profit_hit():
    # Warmup bars, one BUY signal at index 3, then a bar that reaches TP.
    candles = [_ohlc(1.10, 1.10, 1.10, 1.10) for _ in range(4)]
    candles.append(_ohlc(1.10, 1.1050, 1.0995, 1.1050))  # high reaches +40 pips TP
    # Signal fires BUY exactly once, on the bar at index 3.
    calls = {"n": 0}

    def sig(window):
        calls["n"] += 1
        return "BUY" if len(window) == 4 else None

    trades = backtest.simulate(candles, sig, sl_pips=20, tp_pips=40,
                               pip_sz=0.0001, warmup=3)
    assert len(trades) == 1
    assert trades[0]["pips"] == 40  # TP hit


def test_simulate_stop_loss_hit():
    candles = [_ohlc(1.10, 1.10, 1.10, 1.10) for _ in range(4)]
    candles.append(_ohlc(1.10, 1.1005, 1.0975, 1.0980))  # low reaches -20 pips SL

    def sig(window):
        return "BUY" if len(window) == 4 else None

    trades = backtest.simulate(candles, sig, sl_pips=20, tp_pips=40,
                               pip_sz=0.0001, warmup=3)
    assert len(trades) == 1
    assert trades[0]["pips"] == -20


def test_simulate_sl_first_when_bar_touches_both():
    candles = [_ohlc(1.10, 1.10, 1.10, 1.10) for _ in range(4)]
    # This bar spans both SL (-20) and TP (+40); SL must win (conservative).
    candles.append(_ohlc(1.10, 1.1050, 1.0975, 1.10))

    def sig(window):
        return "BUY" if len(window) == 4 else None

    trades = backtest.simulate(candles, sig, 20, 40, 0.0001, warmup=3)
    assert trades[0]["pips"] == -20


def test_summarize_metrics():
    trades = [{"pips": 40}, {"pips": -20}, {"pips": 40}, {"pips": -20}, {"pips": -20}]
    s = backtest.summarize(trades, risk_usd=10, sl_pips=20, tp_pips=40)
    assert s["trades"] == 5 and s["wins"] == 2 and s["losses"] == 3
    # 2 wins * 40 = 80 ; 3 losses * -20 = -60 ; net = 20 pips
    assert s["net_pips"] == 20
    assert abs(s["win_rate"] - 40.0) < 1e-9
    # est $: 2 wins * $10 * (40/20) - 3 losses * $10 = 40 - 30 = $10
    assert s["est_usd"] == 10.0
