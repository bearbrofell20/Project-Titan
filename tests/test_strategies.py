from kalshi_trader.models import Action, Market, Side
from kalshi_trader.strategies.momentum import MovingAverageCrossStrategy
from kalshi_trader.strategies.threshold import MispricingThresholdStrategy


def mkt(ticker="X", yes_bid=None, yes_ask=None, last=None, status="active"):
    return Market(
        ticker=ticker,
        title=ticker,
        status=status,
        yes_bid=yes_bid,
        yes_ask=yes_ask,
        no_bid=None if yes_ask is None else 100 - yes_ask,
        no_ask=None if yes_bid is None else 100 - yes_bid,
        last_price=last,
        volume=0,
    )


# --- threshold strategy ---------------------------------------------------
def test_threshold_buys_cheap_yes():
    s = MispricingThresholdStrategy({"X": 60}, edge_cents=5)
    out = s.generate([mkt("X", yes_bid=50, yes_ask=52)], {})
    assert len(out) == 1
    o = out[0]
    assert o.side is Side.YES and o.action is Action.BUY
    assert o.limit_price_cents == 52  # pays the ask


def test_threshold_buys_no_when_yes_expensive():
    s = MispricingThresholdStrategy({"X": 40}, edge_cents=5)
    out = s.generate([mkt("X", yes_bid=55, yes_ask=57)], {})
    assert len(out) == 1
    o = out[0]
    assert o.side is Side.NO
    assert o.limit_price_cents == 45  # 100 - yes_bid(55)


def test_threshold_no_trade_within_edge():
    s = MispricingThresholdStrategy({"X": 53}, edge_cents=5)
    assert s.generate([mkt("X", yes_bid=50, yes_ask=52)], {}) == []


def test_threshold_ignores_unknown_and_closed_markets():
    s = MispricingThresholdStrategy({"X": 90}, edge_cents=1)
    closed = mkt("X", yes_bid=10, yes_ask=12, status="closed")
    unknown = mkt("Y", yes_bid=10, yes_ask=12)
    assert s.generate([closed, unknown], {}) == []


# --- momentum strategy ----------------------------------------------------
def test_momentum_triggers_on_upward_cross():
    s = MovingAverageCrossStrategy(short_window=2, long_window=4, quantity=1)
    prices = [50, 49, 48, 47, 60, 62]  # falling then a sharp jump up
    all_orders = []
    for p in prices:
        all_orders += s.generate([mkt("X", yes_bid=p - 1, yes_ask=p + 1, last=p)], {})
    # The sharp jump makes the short MA cross above the long MA -> buy Yes.
    assert any(o.side is Side.YES for o in all_orders)


def test_momentum_needs_full_window_before_trading():
    s = MovingAverageCrossStrategy(short_window=2, long_window=4)
    out = s.generate([mkt("X", yes_bid=49, yes_ask=51, last=50)], {})
    assert out == []  # not enough history yet


def test_momentum_only_fires_on_regime_change():
    s = MovingAverageCrossStrategy(short_window=2, long_window=3)
    # steadily rising prices: cross happens once, not every tick
    fires = 0
    for p in [10, 11, 12, 13, 14, 15, 16, 17]:
        out = s.generate([mkt("X", yes_bid=p - 1, yes_ask=p + 1, last=p)], {})
        fires += len(out)
    assert fires <= 1
