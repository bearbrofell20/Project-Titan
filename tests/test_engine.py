from kalshi_trader.config import Config
from kalshi_trader.engine import TradingEngine
from kalshi_trader.models import Action, Market, OrderIntent, Side
from kalshi_trader.strategies.base import Strategy


class _StubStrategy(Strategy):
    name = "stub"

    def __init__(self, intents):
        self._intents = intents

    def generate(self, markets, positions):
        return list(self._intents)


class _StubClient:
    """A client that records submissions instead of hitting the network."""

    def __init__(self):
        self.submitted = []

    def get_markets(self, **kwargs):
        return []

    def get_positions(self):
        return []

    def place_order(self, intent, client_order_id):
        self.submitted.append((intent, client_order_id))
        return {"order": {"order_id": "fake"}}


def _market():
    return Market(
        ticker="X", title="X", status="active",
        yes_bid=49, yes_ask=51, no_bid=49, no_ask=51, last_price=50,
    )


def _intent():
    return OrderIntent(
        ticker="X", action=Action.BUY, side=Side.YES,
        quantity=1, limit_price_cents=51,
    )


def test_dry_run_does_not_submit():
    config = Config(dry_run=True)
    client = _StubClient()
    engine = TradingEngine(config, client, _StubStrategy([_intent()]))
    stats = engine.run_once(markets=[_market()])
    assert stats.orders_approved == 1
    assert stats.orders_submitted == 0
    assert client.submitted == []
    assert len(stats.dry_run_orders) == 1


def test_live_submits_order():
    config = Config(dry_run=False, api_key_id="k", private_key_path="/dev/null")
    client = _StubClient()
    engine = TradingEngine(config, client, _StubStrategy([_intent()]))
    stats = engine.run_once(markets=[_market()])
    assert stats.orders_submitted == 1
    assert len(client.submitted) == 1


def test_risk_rejection_blocks_submit():
    config = Config(dry_run=False, api_key_id="k", private_key_path="/dev/null",
                    max_contracts_per_order=1)
    client = _StubClient()
    big = OrderIntent(ticker="X", action=Action.BUY, side=Side.YES,
                      quantity=5, limit_price_cents=51)
    engine = TradingEngine(config, client, _StubStrategy([big]))
    stats = engine.run_once(markets=[_market()])
    assert stats.orders_rejected == 1
    assert stats.orders_submitted == 0
    assert client.submitted == []
