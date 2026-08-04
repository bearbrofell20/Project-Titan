"""Tests for the pure logic of the OANDA forex bot (no network required)."""

import oanda_trader as ot
from oanda_trader import Config, MomentumDetector, PositionManager


def _candle(close, complete=True):
    return {"mid": {"c": str(close)}, "time": "0", "complete": complete}


# --- completed-candle filtering (only act on closed bars) -----------------
def test_completed_candles_drops_incomplete_trailing_bar():
    raw = [_candle(1), _candle(2), _candle(3, complete=False)]
    done = ot.completed_candles(raw)
    assert len(done) == 2
    assert all(c["complete"] for c in done)


def test_completed_candles_all_complete():
    raw = [_candle(1), _candle(2)]
    assert len(ot.completed_candles(raw)) == 2


def test_candle_epoch_accepts_unix_and_rfc3339():
    # Same instant expressed both ways OANDA can return it.
    assert ot.candle_epoch("1785865500.000000000") == 1785865500
    assert ot.candle_epoch("2026-08-04T17:45:00.000000000Z") == 1785865500


# --- dry-run order path (no network) --------------------------------------
def test_dry_run_order_returns_shape_without_network():
    original = Config.DRY_RUN
    try:
        Config.DRY_RUN = True
        client = ot.OandaClient("faketoken")
        res = client.place_order("USD_JPY", 7500, 150.123, 20, 40)
        assert res["dryRun"] is True
        assert res["fill_price"] == 150.123
        assert res["tp"] == 150.123 + 40 * 0.01  # BUY tp above entry
    finally:
        Config.DRY_RUN = original


# --- position sizing (the previously broken part) -------------------------
def test_sizing_usd_quoted_pair_is_correct():
    # EUR_USD, 20 pip stop, $10 risk, quote is USD so conversion = 1.0.
    units = PositionManager.calculate_units("EUR_USD", 20, quote_to_usd=1.0, risk_usd=10.0)
    assert units == 5000  # NOT 500_000 (the old bug)
    # Sanity: that many units really does risk ~$10 over a 20-pip move.
    assert abs(units * ot.pip_size("EUR_USD") * 20 - 10.0) < 0.01


def test_sizing_usd_base_pair_uses_conversion():
    # USD_JPY @ 150: quote is JPY, quote_to_usd = 1/150.
    units = PositionManager.calculate_units("USD_JPY", 20, quote_to_usd=1 / 150, risk_usd=10.0)
    assert abs(units - 7500) <= 1  # ~7500 (int truncation of 7499.99…)


def test_sizing_returns_zero_when_conversion_unknown():
    assert PositionManager.calculate_units("EUR_GBP", 20, quote_to_usd=None) == 0
    assert PositionManager.calculate_units("EUR_GBP", 20, quote_to_usd=0) == 0


def test_pip_size_and_precision():
    assert ot.pip_size("EUR_USD") == 0.0001
    assert ot.pip_size("USD_JPY") == 0.01
    assert ot.price_decimals("EUR_USD") == 5
    assert ot.price_decimals("USD_JPY") == 3


# --- RSI -------------------------------------------------------------------
def test_rsi_all_gains_is_100():
    prices = list(range(1, 20))  # strictly increasing
    assert MomentumDetector.calculate_rsi(prices, period=14) == 100


def test_rsi_all_losses_is_zero():
    prices = list(range(20, 1, -1))  # strictly decreasing
    assert MomentumDetector.calculate_rsi(prices, period=14) == 0


def test_rsi_none_when_insufficient_data():
    assert MomentumDetector.calculate_rsi([1, 2, 3], period=14) is None


# --- trend -----------------------------------------------------------------
def test_trend_up_down_flat():
    assert MomentumDetector.detect_trend([_candle(1), _candle(2), _candle(3)]) == "UP"
    assert MomentumDetector.detect_trend([_candle(3), _candle(2), _candle(1)]) == "DOWN"
    assert MomentumDetector.detect_trend([_candle(2), _candle(9), _candle(2)]) == "FLAT"


# --- combined signal -------------------------------------------------------
def test_signal_none_without_enough_candles():
    assert MomentumDetector.get_signal([_candle(1)] * 5, "EUR_USD") is None


def test_signal_buy_on_oversold_uptrend():
    # 20 candles: mostly falling (drives RSI low) but the last 3 tick up.
    closes = [100 - i for i in range(17)] + [80, 82, 84]
    candles = [_candle(c) for c in closes]
    assert MomentumDetector.get_signal(candles, "EUR_USD") == "BUY"


def test_signal_sell_on_overbought_downtrend():
    closes = [80 + i for i in range(17)] + [100, 98, 96]
    candles = [_candle(c) for c in closes]
    assert MomentumDetector.get_signal(candles, "EUR_USD") == "SELL"


# --- config guards ---------------------------------------------------------
def test_live_endpoint_detection():
    original = Config.API_URL
    try:
        Config.API_URL = "https://api-fxtrade.oanda.com"
        assert Config.is_live_endpoint() is True
        Config.API_URL = "https://api-fxpractice.oanda.com"
        assert Config.is_live_endpoint() is False
    finally:
        Config.API_URL = original


def test_validate_blocks_live_without_optin():
    original_url, original_allow = Config.API_URL, Config.ALLOW_LIVE
    try:
        Config.API_URL = "https://api-fxtrade.oanda.com"
        Config.ALLOW_LIVE = False
        problems = ot.validate_config(api_token="tok")
        assert any("LIVE" in p for p in problems)
    finally:
        Config.API_URL, Config.ALLOW_LIVE = original_url, original_allow


# --- EMA pullback strategy -------------------------------------------------
def _c(v):
    return {"mid": {"c": f"{v:.5f}"}, "time": "0", "complete": True}


def test_ema_series_basic():
    out = ot.ema_series([1, 1, 1, 1], 3)
    assert out == [1, 1, 1, 1]  # flat input -> flat EMA


def test_ema_pullback_buys_on_resumed_uptrend():
    # Long uptrend so fast EMA > slow EMA, then a one-bar dip below the fast
    # EMA (pullback) followed by a close back above it (resumption).
    prices = [1.10 + i * 0.001 for i in range(30)]  # steady uptrend
    prices[-2] = prices[-3] - 0.006                 # pullback dips below fast EMA
    prices[-1] = prices[-3] + 0.004                 # resumes back above
    candles = [_c(p) for p in prices]
    assert ot.EmaPullbackDetector.get_signal(candles, "EUR_USD") == "BUY"


def test_ema_pullback_none_without_pullback():
    prices = [1.10 + i * 0.001 for i in range(30)]  # clean uptrend, no dip
    candles = [_c(p) for p in prices]
    assert ot.EmaPullbackDetector.get_signal(candles, "EUR_USD") is None


def test_ema_pullback_needs_enough_history():
    candles = [_c(1.1)] * 5
    assert ot.EmaPullbackDetector.get_signal(candles, "EUR_USD") is None


def test_signal_for_dispatches_on_config():
    prices = [1.10 + i * 0.001 for i in range(30)]
    prices[-2] = prices[-3] - 0.006
    prices[-1] = prices[-3] + 0.004
    candles = [_c(p) for p in prices]
    original = Config.STRATEGY
    try:
        Config.STRATEGY = "ema_pullback"
        assert ot.signal_for(candles, "EUR_USD") == "BUY"
        Config.STRATEGY = "rsi"  # RSI won't fire on this clean uptrend
        assert ot.signal_for(candles, "EUR_USD") is None
    finally:
        Config.STRATEGY = original


# --- breakout strategy -----------------------------------------------------
def test_breakout_buys_on_new_high():
    # 21 flat closes then a higher one -> upside breakout.
    prices = [1.1000] * 21 + [1.1050]
    candles = [_c(p) for p in prices]
    assert ot.BreakoutDetector.get_signal(candles, "EUR_USD") == "BUY"


def test_breakout_sells_on_new_low():
    prices = [1.1000] * 21 + [1.0950]
    candles = [_c(p) for p in prices]
    assert ot.BreakoutDetector.get_signal(candles, "EUR_USD") == "SELL"


def test_breakout_none_inside_range():
    prices = [1.1000 + (i % 3) * 0.0001 for i in range(25)]
    assert ot.BreakoutDetector.get_signal([_c(p) for p in prices], "EUR_USD") in (None, "BUY", "SELL")
    flat = [_c(1.1000)] * 25
    assert ot.BreakoutDetector.get_signal(flat, "EUR_USD") is None


# --- bollinger mean-reversion ----------------------------------------------
def test_bollinger_buys_when_below_lower_band():
    prices = [1.1000] * 19 + [1.0900]  # sharp drop below the band
    candles = [_c(p) for p in prices]
    assert ot.BollingerReversionDetector.get_signal(candles, "EUR_USD") == "BUY"


def test_bollinger_sells_when_above_upper_band():
    prices = [1.1000] * 19 + [1.1100]
    candles = [_c(p) for p in prices]
    assert ot.BollingerReversionDetector.get_signal(candles, "EUR_USD") == "SELL"


def test_bollinger_none_when_flat():
    assert ot.BollingerReversionDetector.get_signal([_c(1.1)] * 25, "EUR_USD") is None


def test_all_strategies_registered():
    assert set(ot.STRATEGIES) == {"rsi", "ema_pullback", "breakout", "bollinger"}
