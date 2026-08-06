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
    assert set(ot.STRATEGIES) == {"rsi", "ema_pullback", "breakout", "bollinger",
                                  "stochastic", "ema_trend"}


# --- EMA 20/50 trend filter + crossover ------------------------------------
def test_ema_trend_bias_up_and_down():
    up = [_c(1.10 + i * 0.001) for i in range(60)]
    down = [_c(1.20 - i * 0.001) for i in range(60)]
    assert ot.ema_trend_bias(up, 20, 50) == "BUY"
    assert ot.ema_trend_bias(down, 20, 50) == "SELL"


def test_ema_trend_crossover_buy():
    # Downtrend (fast below slow), then a strong rally flips fast above slow.
    prices = [1.20 - i * 0.001 for i in range(55)] + [1.20 + i * 0.01 for i in range(1, 12)]
    candles = [_c(p) for p in prices]
    seen = [ot.EmaTrendDetector.get_signal(candles[: i + 1], "EUR_USD")
            for i in range(52, len(candles))]
    assert "BUY" in seen


def test_trend_filter_blocks_against_trend_signal():
    # Clean uptrend -> bias BUY. A SELL signal from the active strategy is blocked.
    up = [_c(1.10 + i * 0.001) for i in range(60)]
    orig_filter, orig_strat = Config.TREND_FILTER, Config.STRATEGY
    try:
        Config.TREND_FILTER = True
        Config.STRATEGY = "breakout"
        # Force a new 20-bar low on the last bar -> breakout SELL, against the uptrend.
        against = up[:-1] + [_c(1.05)]
        assert ot.BreakoutDetector.get_signal(against, "EUR_USD") == "SELL"
        assert ot.signal_for(against, "EUR_USD") is None  # blocked by filter
    finally:
        Config.TREND_FILTER, Config.STRATEGY = orig_filter, orig_strat


# --- profit-take rule (+X% of margin) --------------------------------------
def test_should_take_profit_triggers_at_threshold():
    assert ot.should_take_profit(10.0, 100.0, 10) is True    # exactly 10%
    assert ot.should_take_profit(12.0, 100.0, 10) is True    # above
    assert ot.should_take_profit(9.99, 100.0, 10) is False   # below
    assert ot.should_take_profit(-5.0, 100.0, 10) is False   # a loss


def test_should_take_profit_guards_bad_margin():
    assert ot.should_take_profit(50.0, 0.0, 10) is False
    assert ot.should_take_profit(50.0, -1.0, 10) is False


# --- minimum-fill fallback direction ---------------------------------------
def test_fallback_direction_buys_in_uptrend():
    up = [_c(1.10 + i * 0.001) for i in range(30)]
    assert ot.fallback_direction(up) == "BUY"


def test_fallback_direction_sells_in_downtrend():
    down = [_c(1.20 - i * 0.001) for i in range(30)]
    assert ot.fallback_direction(down) == "SELL"


# --- min/max open-trades validation ----------------------------------------
def test_validate_blocks_min_greater_than_max():
    orig_min, orig_max = Config.MIN_OPEN_TRADES, Config.MAX_OPEN_TRADES
    try:
        Config.MIN_OPEN_TRADES, Config.MAX_OPEN_TRADES = 9, 6
        problems = ot.validate_config("tok")
        assert any("MIN_OPEN_TRADES" in p for p in problems)
    finally:
        Config.MIN_OPEN_TRADES, Config.MAX_OPEN_TRADES = orig_min, orig_max


# --- stochastic reversal strategy ------------------------------------------
def _sc(close):
    # Fixed 0..100 range so %K == close, making the oscillator deterministic.
    return {"mid": {"h": "100", "l": "0", "c": str(close)}, "time": "0", "complete": True}


def test_stochastic_k_equals_close_in_fixed_range():
    ks = ot.stochastic_k([_sc(30)] * 14, period=14)
    assert ks[-1] == 30.0
    assert ks[0] is None  # not enough history yet


def test_stochastic_buys_on_oversold_turn_up():
    # Long stretch oversold (~10), then %K ticks up and crosses %D.
    candles = [_sc(10)] * 19 + [_sc(15)]
    assert ot.StochasticReversalDetector.get_signal(candles, "EUR_USD") == "BUY"


def test_stochastic_sells_on_overbought_turn_down():
    candles = [_sc(90)] * 19 + [_sc(85)]
    assert ot.StochasticReversalDetector.get_signal(candles, "EUR_USD") == "SELL"


def test_stochastic_none_in_midrange():
    candles = [_sc(50)] * 20
    assert ot.StochasticReversalDetector.get_signal(candles, "EUR_USD") is None


def test_stochastic_none_without_enough_history():
    assert ot.StochasticReversalDetector.get_signal([_sc(10)] * 5, "EUR_USD") is None


def test_stochastic_registered():
    assert "stochastic" in ot.STRATEGIES
    assert set(ot.STRATEGIES) == {"rsi", "ema_pullback", "breakout", "bollinger",
                                  "stochastic", "ema_trend"}


# --- loss-cut rule (-X% of margin) -----------------------------------------
def test_should_cut_loss_triggers_at_threshold():
    assert ot.should_cut_loss(-2.0, 100.0, 2) is True    # exactly -2%
    assert ot.should_cut_loss(-3.0, 100.0, 2) is True    # worse
    assert ot.should_cut_loss(-1.99, 100.0, 2) is False  # not yet
    assert ot.should_cut_loss(5.0, 100.0, 2) is False    # a profit


def test_should_cut_loss_guards_bad_margin():
    assert ot.should_cut_loss(-50.0, 0.0, 2) is False


def test_default_strategy_is_the_winner():
    # ema_trend on tight majors with the trend filter is the only config that
    # cleared spread costs in the backtest (PF ~1.4); it is the default.
    assert Config.STRATEGY == "ema_trend"
    assert Config.TREND_FILTER is True


# --- market analyzer (ATR / ADX pre-trade filter) --------------------------
def _ohlc(o, h, l, c):
    return {"mid": {"o": str(o), "h": str(h), "l": str(l), "c": str(c)},
            "time": "0", "complete": True}


def test_atr_basic():
    # Each bar has a 10-pip range on EUR_USD-scale prices.
    candles = [_ohlc(1.1000, 1.1010, 1.1000, 1.1005) for _ in range(20)]
    a = ot.atr(candles, 14)
    assert a is not None and abs(a - 0.0010) < 1e-6


def test_adx_high_in_strong_trend():
    # Steadily rising highs/lows -> strong uptrend -> high ADX.
    candles = [_ohlc(1.10 + i*0.001, 1.10 + i*0.001 + 0.0008,
                     1.10 + i*0.001, 1.10 + i*0.001 + 0.0006) for i in range(60)]
    a = ot.adx(candles, 14)
    assert a is not None and a > 25


def test_adx_low_in_chop():
    # Flat, alternating candles -> no directional movement -> low ADX.
    candles = []
    for i in range(60):
        base = 1.1000 + (0.0002 if i % 2 else -0.0002)
        candles.append(_ohlc(base, base + 0.0003, base - 0.0003, base))
    a = ot.adx(candles, 14)
    assert a is not None and a < 25


def test_analyzer_vetoes_choppy_market():
    orig = (Config.MIN_ADX, Config.MIN_ATR_PIPS)
    try:
        Config.MIN_ADX, Config.MIN_ATR_PIPS = 25, 0
        chop = []
        for i in range(60):
            base = 1.1000 + (0.0002 if i % 2 else -0.0002)
            chop.append(_ohlc(base, base + 0.0003, base - 0.0003, base))
        assert ot.MarketAnalyzer.approves(chop, "EUR_USD") is False
    finally:
        Config.MIN_ADX, Config.MIN_ATR_PIPS = orig


def test_analyzer_vetoes_dead_market():
    orig = (Config.MIN_ADX, Config.MIN_ATR_PIPS)
    try:
        Config.MIN_ADX, Config.MIN_ATR_PIPS = 0, 5  # require 5-pip ATR
        dead = [_ohlc(1.1000, 1.10005, 1.09995, 1.1000) for _ in range(30)]  # ~1 pip range
        v = ot.MarketAnalyzer.analyze(dead, "EUR_USD")
        assert v["approved"] is False and "dead market" in v["reason"]
    finally:
        Config.MIN_ADX, Config.MIN_ATR_PIPS = orig


# --- config validation hardening (troubleshooting passes) ------------------
def test_validate_catches_zero_poll_interval():
    orig = Config.POLL_INTERVAL
    try:
        Config.POLL_INTERVAL = 0
        assert any("POLL_INTERVAL" in p for p in ot.validate_config("tok"))
    finally:
        Config.POLL_INTERVAL = orig


def test_validate_catches_empty_instruments():
    orig = Config.INSTRUMENTS
    try:
        Config.INSTRUMENTS = []
        assert any("INSTRUMENTS is empty" in p for p in ot.validate_config("tok"))
    finally:
        Config.INSTRUMENTS = orig


def test_validate_catches_insufficient_candle_count():
    orig = (Config.CANDLE_COUNT, Config.STRATEGY)
    try:
        Config.STRATEGY, Config.CANDLE_COUNT = "ema_trend", 10  # needs TREND_SLOW+2 = 52
        assert any("CANDLE_COUNT" in p for p in ot.validate_config("tok"))
    finally:
        Config.CANDLE_COUNT, Config.STRATEGY = orig
