"""Offline tests for the dashboard state builder (no network)."""

import dashboard
from oanda_trader import Config


class FakeClient:
    """Minimal stand-in for OandaClient covering what the dashboard calls."""

    def get_account_details(self):
        return {
            "id": "101-001-000-001", "currency": "USD", "balance": "100251.16",
            "NAV": "100251.16", "unrealizedPL": "0.0", "pl": "1.16",
            "marginUsed": "95.26", "marginCloseoutPercent": "0.0005",
            "openTradeCount": 1,
        }

    def _request(self, method, path, **kw):
        assert "openPositions" in path
        return {"positions": [
            {"instrument": "AUD_USD",
             "long": {"units": "150", "averagePrice": "0.70388"},
             "short": {"units": "0"}, "unrealizedPL": "0.0225"},
        ]}

    def get_candles(self, inst, granularity="M5", count=60):
        # 25 completed candles, gently rising -> known trend, valid RSI.
        return [{"mid": {"c": f"{1.10 + i*0.0001:.5f}"}, "time": str(i),
                 "complete": True} for i in range(25)]


def test_build_state_shape_and_values():
    state = dashboard.build_state(FakeClient())
    assert state["status"] == "ok"
    assert state["account"]["balance"] == 100251.16
    assert state["account"]["realizedPL"] == 1.16
    # margin closeout percent is scaled to a percentage
    assert abs(state["account"]["marginCloseoutPercent"] - 0.05) < 1e-6

    assert len(state["positions"]) == 1
    assert state["positions"][0]["instrument"] == "AUD_USD"
    assert state["positions"][0]["units"] == 150

    assert len(state["market"]) == len(Config.INSTRUMENTS)
    row = state["market"][0]
    assert row["price"] is not None and row["rsi"] is not None
    assert row["trend"] in ("UP", "DOWN", "FLAT")


def test_build_state_reports_error_when_account_unreachable():
    class Dead:
        def get_account_details(self):
            return {}
    state = dashboard.build_state(Dead())
    assert state["status"] == "error"
