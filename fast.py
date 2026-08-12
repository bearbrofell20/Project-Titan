"""Vectorized (single-pass) indicators for fast backtesting.

The live detectors recompute indicators over a growing window each bar, which is
O(n^2) — fine for a 30-bar live tick, fatal for a 25k-bar backtest. These build
the whole per-bar series in one O(n) pass so validation and parameter sweeps are
quick. They compute standard Wilder ATR/ADX and EMA-crossover signals; sanity
tests in ``tests/test_fast.py`` check them against the live functions.
"""

from __future__ import annotations

from typing import List, Optional


def _ohlc(c):
    m = c["mid"]
    return float(m["o"]), float(m["h"]), float(m["l"]), float(m["c"])


def ema_series(closes: List[float], period: int) -> List[float]:
    if not closes:
        return []
    k = 2.0 / (period + 1)
    out = [closes[0]]
    for v in closes[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def ema_cross_signals(candles: List[dict], fast: int = 20, slow: int = 50) -> List[Optional[str]]:
    """One signal per bar: 'BUY' on a fast>slow up-cross, 'SELL' on a down-cross,
    else None. Mirrors EmaTrendDetector but computed in a single pass."""
    closes = [_ohlc(c)[3] for c in candles]
    ef, es = ema_series(closes, fast), ema_series(closes, slow)
    out: List[Optional[str]] = [None] * len(candles)
    for i in range(1, len(candles)):
        if i < slow + 1:
            continue
        prev, now = ef[i - 1] - es[i - 1], ef[i] - es[i]
        if prev <= 0 and now > 0:
            out[i] = "BUY"
        elif prev >= 0 and now < 0:
            out[i] = "SELL"
    return out


def donchian_breakout_signals(candles: List[dict], lookback: int = 20) -> List[Optional[str]]:
    """Volatility-expansion breakout: BUY when the close makes a new `lookback`-bar
    high, SELL on a new `lookback`-bar low. One signal per bar."""
    closes = [_ohlc(c)[3] for c in candles]
    out: List[Optional[str]] = [None] * len(candles)
    for i in range(lookback, len(candles)):
        hi = max(closes[i - lookback:i])
        lo = min(closes[i - lookback:i])
        if closes[i] > hi:
            out[i] = "BUY"
        elif closes[i] < lo:
            out[i] = "SELL"
    return out


def bollinger_reversion_signals(candles: List[dict], period: int = 20, k: float = 2.0) -> List[Optional[str]]:
    """Mean-reversion: BUY when close pierces below the lower band, SELL when it
    pierces above the upper band (fade the extreme)."""
    import statistics
    closes = [_ohlc(c)[3] for c in candles]
    out: List[Optional[str]] = [None] * len(candles)
    for i in range(period, len(candles)):
        w = closes[i - period:i]
        mean = sum(w) / period
        sd = statistics.pstdev(w)
        if sd == 0:
            continue
        if closes[i] < mean - k * sd:
            out[i] = "BUY"
        elif closes[i] > mean + k * sd:
            out[i] = "SELL"
    return out


def opening_range_breakout_signals(
    candles: List[dict],
    open_hour: int = 7,       # session open in UTC (7 = London, 13 = NY)
    range_bars: int = 4,      # bars after the open that define the range
    window_end_hour: int = 11,  # stop taking new breakouts after this UTC hour
) -> List[Optional[str]]:
    """Opening-range breakout: each day, the first ``range_bars`` after
    ``open_hour`` set a high/low box; the first close to break out (within the
    session window) fires BUY (above) or SELL (below). One entry per day.

    Economic rationale: liquidity and order flow arrive at the session open, so a
    decisive break of the opening range tends to continue — a *structural* effect,
    not a fitted parameter. Days/hours are derived from the candle epoch (UTC).
    """
    out: List[Optional[str]] = [None] * len(candles)

    def hour(t):
        return int((t // 3600) % 24)

    def day(t):
        return t // 86400

    cur_day = None
    hi = lo = None
    seen = 0
    fired = False
    for i, c in enumerate(candles):
        t = c["time"]
        d = day(t)
        h = hour(t)
        if d != cur_day:                    # new UTC day -> reset the box
            cur_day, hi, lo, seen, fired = d, None, None, 0, False
        if h < open_hour or h > window_end_hour:
            continue
        m = c["mid"]
        hi_i, lo_i, close = float(m["h"]), float(m["l"]), float(m["c"])
        if seen < range_bars:               # building the opening range
            hi = hi_i if hi is None else max(hi, hi_i)
            lo = lo_i if lo is None else min(lo, lo_i)
            seen += 1
            continue
        if fired or hi is None:
            continue
        if close > hi:
            out[i] = "BUY"; fired = True
        elif close < lo:
            out[i] = "SELL"; fired = True
    return out


def macd_cross_signals(candles: List[dict], fast: int = 12, slow: int = 26, sig: int = 9) -> List[Optional[str]]:
    """MACD(12,26,9): BUY when the MACD line crosses above its signal line,
    SELL when it crosses below. (Sarwa 'trend trading' via MACD.)"""
    closes = [_ohlc(c)[3] for c in candles]
    ef, es = ema_series(closes, fast), ema_series(closes, slow)
    macd = [ef[i] - es[i] for i in range(len(closes))]
    signal = ema_series(macd, sig)
    out: List[Optional[str]] = [None] * len(candles)
    for i in range(slow + sig, len(candles)):
        prev, now = macd[i - 1] - signal[i - 1], macd[i] - signal[i]
        if prev <= 0 and now > 0:
            out[i] = "BUY"
        elif prev >= 0 and now < 0:
            out[i] = "SELL"
    return out


def ma_ribbon_signals(candles: List[dict], a: int = 5, b: int = 8, c: int = 13) -> List[Optional[str]]:
    """5/8/13 EMA ribbon (Sarwa 'scalping'): BUY the bar the ribbon lines up
    bullish (a>b>c) after not being, SELL when it lines up bearish (a<b<c)."""
    closes = [_ohlc(x)[3] for x in candles]
    ea, eb, ec = ema_series(closes, a), ema_series(closes, b), ema_series(closes, c)
    out: List[Optional[str]] = [None] * len(candles)
    def aligned(i):
        if ea[i] > eb[i] > ec[i]:
            return "BUY"
        if ea[i] < eb[i] < ec[i]:
            return "SELL"
        return None
    for i in range(c + 1, len(candles)):
        now, prev = aligned(i), aligned(i - 1)
        if now and now != prev:
            out[i] = now
    return out


def _sma(vals, i, n):
    if i + 1 < n:
        return None
    return sum(vals[i - n + 1:i + 1]) / n


def _std(vals, i, n):
    if i + 1 < n:
        return None
    w = vals[i - n + 1:i + 1]
    m = sum(w) / n
    return (sum((x - m) ** 2 for x in w) / n) ** 0.5


def breakout_retest_signals(candles, lookback=20, retest_bars=6, tol_frac=0.0005):
    """Breakout + RETEST (spec C): price breaks the `lookback`-bar high/low, then
    must pull back to the broken level and CLOSE back through it (rejection)
    within `retest_bars`. One-shot per setup — avoids chasing the first candle."""
    closes = [_ohlc(c)[3] for c in candles]
    highs = [_ohlc(c)[1] for c in candles]
    lows = [_ohlc(c)[2] for c in candles]
    out = [None] * len(candles)
    armed = None  # (dir, level, bars_left)
    for i in range(lookback + 1, len(candles)):
        hi = max(highs[i - lookback:i])
        lo = min(lows[i - lookback:i])
        if armed:
            d, lvl, left = armed
            left -= 1
            if left <= 0:
                armed = None
            elif d == "BUY" and lows[i] <= lvl * (1 + tol_frac) and closes[i] > lvl:
                out[i] = "BUY"; armed = None
            elif d == "SELL" and highs[i] >= lvl * (1 - tol_frac) and closes[i] < lvl:
                out[i] = "SELL"; armed = None
            else:
                armed = (d, lvl, left)
        if armed is None:
            if closes[i] > hi:
                armed = ("BUY", hi, retest_bars)
            elif closes[i] < lo:
                armed = ("SELL", lo, retest_bars)
    return out


def squeeze_expansion_signals(candles, period=20, bb_k=2.0, kc_k=1.5, atr_p=20):
    """Volatility squeeze -> expansion (spec F): Bollinger band inside Keltner
    channel = compression; fire in the breakout direction the bar the squeeze
    releases. BUY if releasing with close above the mean, SELL if below."""
    closes = [_ohlc(c)[3] for c in candles]
    ema_mid = ema_series(closes, period)
    atr = atr_series(candles, atr_p)
    out = [None] * len(candles)
    squeezed_prev = False
    for i in range(len(candles)):
        sd = _std(closes, i, period)
        sma = _sma(closes, i, period)
        if sd is None or atr[i] is None:
            continue
        bb_u, bb_l = sma + bb_k * sd, sma - bb_k * sd
        kc_u, kc_l = ema_mid[i] + kc_k * atr[i], ema_mid[i] - kc_k * atr[i]
        squeezed = bb_u < kc_u and bb_l > kc_l
        if squeezed_prev and not squeezed:  # squeeze just released
            out[i] = "BUY" if closes[i] > ema_mid[i] else "SELL"
        squeezed_prev = squeezed
    return out


def swing_pullback_signals(candles, swing=5, ema_trend=50, atr_p=14):
    """Structure swing pullback (spec A): in an uptrend (price > slow EMA and a
    higher-low structure), BUY when price pulls back near the last swing low and
    turns up; mirror for downtrend. Uses market structure, not just indicators."""
    o = [_ohlc(c) for c in candles]
    closes = [x[3] for x in o]
    highs = [x[1] for x in o]
    lows = [x[2] for x in o]
    ema = ema_series(closes, ema_trend)
    out = [None] * len(candles)
    for i in range(swing * 2 + ema_trend, len(candles)):
        # last confirmed swing low/high (pivot `swing` bars back)
        p = i - swing
        is_low = all(lows[p] <= lows[p + k] for k in range(-swing, swing + 1) if k)
        is_high = all(highs[p] >= highs[p + k] for k in range(-swing, swing + 1) if k)
        up = closes[i] > ema[i]
        dn = closes[i] < ema[i]
        # pullback + turn-up in an uptrend
        if up and is_low and lows[i - 1] <= lows[p] * 1.001 and closes[i] > closes[i - 1]:
            out[i] = "BUY"
        elif dn and is_high and highs[i - 1] >= highs[p] * 0.999 and closes[i] < closes[i - 1]:
            out[i] = "SELL"
    return out


def atr_series(candles: List[dict], period: int = 14) -> List[Optional[float]]:
    """ATR per bar, matching oanda_trader.atr (simple mean of the last `period`
    true ranges). None until `period` bars of history exist at that index."""
    n = len(candles)
    out: List[Optional[float]] = [None] * n
    if n < period + 1:
        return out
    tr = [0.0] * n  # tr[i] is the true range at candle i (i>=1)
    for i in range(1, n):
        _o, h, l, _c = _ohlc(candles[i])
        pc = _ohlc(candles[i - 1])[3]
        tr[i] = max(h - l, abs(h - pc), abs(l - pc))
    run = sum(tr[1:period + 1])
    out[period] = run / period
    for i in range(period + 1, n):
        run += tr[i] - tr[i - period]
        out[i] = run / period
    return out


def _wilder(values: List[float], period: int) -> List[float]:
    """Wilder running smoothing — matches oanda_trader._wilder."""
    if len(values) < period:
        return []
    out = [sum(values[:period])]
    for v in values[period:]:
        out.append(out[-1] - out[-1] / period + v)
    return out


def adx_series(candles: List[dict], period: int = 14) -> List[Optional[float]]:
    """ADX per bar, matching oanda_trader.adx (simple mean of the last `period`
    DX values). None until 2*period+1 bars of history exist at that index.
    """
    n = len(candles)
    out: List[Optional[float]] = [None] * n
    if n < 2 * period + 1:
        return out
    plus_dm, minus_dm, tr = [], [], []
    for i in range(1, n):
        _o, h, l, _c = _ohlc(candles[i])
        ph, pl = _ohlc(candles[i - 1])[1], _ohlc(candles[i - 1])[2]
        pc = _ohlc(candles[i - 1])[3]
        up, down = h - ph, pl - l
        plus_dm.append(up if (up > down and up > 0) else 0.0)
        minus_dm.append(down if (down > up and down > 0) else 0.0)
        tr.append(max(h - l, abs(h - pc), abs(l - pc)))

    str_, sp, sm = _wilder(tr, period), _wilder(plus_dm, period), _wilder(minus_dm, period)
    dx = []
    for st, p, m in zip(str_, sp, sm):
        if st == 0:
            dx.append(0.0); continue
        pdi, mdi = 100 * p / st, 100 * m / st
        denom = pdi + mdi
        dx.append(100 * abs(pdi - mdi) / denom if denom else 0.0)
    # dx[k] aligns to candle index (period + k); ADX at that index is the mean of
    # the last `period` dx values available up to it (matching the live function).
    for k in range(len(dx)):
        idx = period + k
        if k + 1 >= period:
            window = dx[k + 1 - period: k + 1]
            out[idx] = sum(window) / len(window)
    return out
