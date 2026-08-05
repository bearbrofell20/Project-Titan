"""Offline tests for the unified dashboard state builder (no network)."""

import dashboard
from kalshi_trader.models import Position
from oanda_trader import Config


class FakeOanda:
    """Minimal stand-in for OandaClient covering what the dashboard calls."""

    def get_account_details(self):
        return {
            "id": "101-001-000-001", "currency": "USD", "balance": "100251.16",
            "NAV": "100251.16", "unrealizedPL": "0.0", "pl": "1.16",
            "marginUsed": "95.26", "openTradeCount": 1,
        }

    def _request(self, method, path, **kw):
        assert "openPositions" in path
        return {"positions": [
            {"instrument": "AUD_USD",
             "long": {"units": "150", "averagePrice": "0.70388"},
             "short": {"units": "0"}, "unrealizedPL": "0.0225"},
        ]}

    def get_candles(self, inst, granularity="M5", count=60):
        out = []
        for i in range(25):
            c = 1.10 + i * 0.0001
            out.append({"mid": {"o": f"{c:.5f}", "h": f"{c + 0.0005:.5f}",
                                 "l": f"{c - 0.0005:.5f}", "c": f"{c:.5f}"},
                        "time": str(i), "complete": True})
        return out


class FakeKalshi:
    def get_balance_cents(self):
        return 250000  # $2,500.00

    def get_positions(self):
        return [Position(ticker="ABC-24", quantity=10, avg_price_cents=45)]


# --- combined state --------------------------------------------------------
def test_state_has_both_venues():
    state = dashboard.build_state(FakeOanda(), FakeKalshi())
    assert set(state["venues"]) == {"oanda", "kalshi"}


def test_oanda_venue_ok():
    v = dashboard.build_oanda_venue(FakeOanda())
    assert v["status"] == "ok"
    assert v["account"]["balance"] == 100251.16
    assert v["account"]["realizedPL"] == 1.16
    assert v["positions"][0]["instrument"] == "AUD_USD"
    assert len(v["market"]) == len(Config.INSTRUMENTS)
    assert v["market"][0]["rsi"] is not None


def test_oanda_venue_not_configured_when_no_client():
    v = dashboard.build_oanda_venue(None)
    assert v["status"] == "not_configured"


def test_oanda_venue_error_when_unreachable():
    class Dead:
        def get_account_details(self):
            return {}
    assert dashboard.build_oanda_venue(Dead())["status"] == "error"


# --- kalshi venue ----------------------------------------------------------
def test_kalshi_venue_ok():
    v = dashboard.build_kalshi_venue(FakeKalshi())
    assert v["status"] == "ok"
    assert v["account"]["balance"] == 2500.0
    p = v["positions"][0]
    assert p["ticker"] == "ABC-24" and p["quantity"] == 10
    assert p["avgPriceCents"] == 45


def test_kalshi_venue_not_configured_when_no_client():
    v = dashboard.build_kalshi_venue(None)
    assert v["status"] == "not_configured"


def test_kalshi_venue_error_on_exception():
    class Boom:
        def get_balance_cents(self):
            raise RuntimeError("auth failed")
    assert dashboard.build_kalshi_venue(Boom())["status"] == "error"
