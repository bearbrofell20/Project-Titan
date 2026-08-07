"""Fast vectorized indicators must match the live functions exactly, and the
signal precompute must match the live detector — otherwise the backtest isn't
testing what the bot trades."""

import fast
import oanda_trader as ot


def _c(o, h, l, c, t=0):
    return {"mid": {"o": str(o), "h": str(h), "l": str(l), "c": str(c)}, "time": str(t)}


def _series(n=400):
    # deterministic pseudo-random walk with range, enough bars for ADX
    import random
    random.seed(7)
    out = []
    price = 1.1000
    for i in range(n):
        drift = random.uniform(-0.0006, 0.0006)
        o = price
        c = price + drift
        h = max(o, c) + random.uniform(0, 0.0004)
        l = min(o, c) - random.uniform(0, 0.0004)
        out.append(_c(o, h, l, c, i))
        price = c
    return out


def test_fast_atr_matches_live():
    c = _series()
    fa = fast.atr_series(c, 14)
    for i in range(20, len(c), 13):
        assert abs(fa[i] - ot.atr(c[: i + 1], 14)) < 1e-12


def test_fast_adx_matches_live():
    c = _series()
    fx = fast.adx_series(c, 14)
    for i in range(40, len(c), 11):
        live = ot.adx(c[: i + 1], 14)
        if live is not None and fx[i] is not None:
            assert abs(fx[i] - live) < 1e-9


def test_fast_ema_cross_matches_detector():
    c = _series()
    sig = fast.ema_cross_signals(c, ot.Config.TREND_FAST, ot.Config.TREND_SLOW)
    for i in range(60, len(c)):
        live = ot.EmaTrendDetector.get_signal(c[: i + 1], "EUR_USD")
        assert (sig[i] or None) == (live or None)


def test_donchian_breakout_direction():
    # flat then a decisive new high -> BUY
    flat = [_c(1.10, 1.10, 1.10, 1.10, i) for i in range(25)]
    flat.append(_c(1.10, 1.11, 1.10, 1.105, 25))
    sig = fast.donchian_breakout_signals(flat, lookback=20)
    assert sig[-1] == "BUY"


def test_bollinger_reversion_direction():
    # a window with real (small) variance, then a close far below the lower band
    base = [_c(1.10, 1.10, 1.10, 1.10 + (0.0001 if i % 2 else -0.0001), i)
            for i in range(20)]
    base.append(_c(1.10, 1.10, 1.09, 1.0900, 20))   # sharp drop -> BUY (fade)
    sig = fast.bollinger_reversion_signals(base, period=20, k=2.0)
    assert sig[-1] == "BUY"
