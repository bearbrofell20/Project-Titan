import pytest

from kalshi_trader.models import (
    Action,
    Market,
    OrderIntent,
    OrderType,
    Position,
    Side,
)


def test_market_from_api_and_mid():
    m = Market.from_api(
        {
            "ticker": "ABC-24",
            "title": "Will X happen?",
            "status": "active",
            "yes_bid": 40,
            "yes_ask": 44,
            "no_bid": 56,
            "no_ask": 60,
            "last_price": 42,
            "volume": 1000,
        }
    )
    assert m.is_tradable
    assert m.yes_mid == 42.0


def test_market_mid_none_when_one_sided():
    m = Market.from_api({"ticker": "X", "status": "active", "yes_bid": 40})
    assert m.yes_mid is None


def test_order_intent_validates_price_range():
    with pytest.raises(ValueError):
        OrderIntent(
            ticker="X",
            action=Action.BUY,
            side=Side.YES,
            quantity=1,
            order_type=OrderType.LIMIT,
            limit_price_cents=0,
        )
    with pytest.raises(ValueError):
        OrderIntent(
            ticker="X",
            action=Action.BUY,
            side=Side.YES,
            quantity=1,
            order_type=OrderType.LIMIT,
            limit_price_cents=100,
        )


def test_order_intent_requires_positive_quantity():
    with pytest.raises(ValueError):
        OrderIntent(ticker="X", action=Action.BUY, side=Side.YES, quantity=0)


def test_to_api_payload_yes_and_no_price_fields():
    yes = OrderIntent(
        ticker="X",
        action=Action.BUY,
        side=Side.YES,
        quantity=3,
        limit_price_cents=55,
    ).to_api_payload("cid-1")
    assert yes["yes_price"] == 55 and "no_price" not in yes
    assert yes["count"] == 3 and yes["action"] == "buy"

    no = OrderIntent(
        ticker="X",
        action=Action.BUY,
        side=Side.NO,
        quantity=2,
        limit_price_cents=45,
    ).to_api_payload("cid-2")
    assert no["no_price"] == 45 and "yes_price" not in no


def test_position_exposure():
    p = Position(ticker="X", quantity=-4, avg_price_cents=30)
    assert p.exposure_cents == 120
