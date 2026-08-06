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

    def __init__(self, balance_cents=1_000_00, positions=None):
        self.submitted = []
        self.balance_cents = balance_cents
        self._positions = positions or []

    def get_markets(self, **kwargs):
        return []

    def get_positions(self):
        return list(self._positions)

    def get_balance_cents(self):
        return self.balance_cents

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


# --- Kalshi rules: cash floor + cash-out ------------------------------------
from kalshi_trader.models import Position


def test_no_entries_below_cash_floor():
    # Available cash $3 < $5 floor -> strategy entry must be blocked.
    config = Config(dry_run=False, api_key_id="k", private_key_path="/dev/null",
                    min_cash_cents=5_00)
    client = _StubClient(balance_cents=3_00)
    engine = TradingEngine(config, client, _StubStrategy([_intent()]))
    engine.run_once(markets=[_market()])
    assert client.submitted == []           # nothing opened
    assert engine.stats.orders_submitted == 0


def test_entries_allowed_above_cash_floor():
    config = Config(dry_run=False, api_key_id="k", private_key_path="/dev/null",
                    min_cash_cents=5_00)
    client = _StubClient(balance_cents=50_00)
    engine = TradingEngine(config, client, _StubStrategy([_intent()]))
    engine.run_once(markets=[_market()])
    assert engine.stats.orders_submitted == 1


def test_cash_out_positive_position():
    # Hold 10 Yes @ 40c; market yes_bid is 49c -> profitable -> auto cash-out.
    config = Config(dry_run=False, api_key_id="k", private_key_path="/dev/null")
    pos = Position(ticker="X", quantity=10, avg_price_cents=40)
    client = _StubClient(balance_cents=50_00, positions=[pos])
    engine = TradingEngine(config, client, _StubStrategy([]))
    engine.run_once(markets=[_market()])   # _market has yes_bid=49
    # A closing SELL YES order was submitted for the position.
    assert any(i.action is Action.SELL and i.side is Side.YES and i.quantity == 10
               for i, _ in client.submitted)
