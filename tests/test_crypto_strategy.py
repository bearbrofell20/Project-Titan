from datetime import datetime, timedelta, timezone

from kalshi_trader.models import Action, Market, Side
from kalshi_trader.strategies.crypto import CryptoFairValueStrategy


def _future(mins=10):
    return (datetime.now(timezone.utc) + timedelta(minutes=mins)).isoformat().replace("+00:00", "Z")


def _mkt(strike, yes_bid, yes_ask, mins=10):
    return Market(ticker="KXBTC15M-X", title="BTC", status="active",
                  yes_bid=yes_bid, yes_ask=yes_ask, no_bid=100 - yes_ask, no_ask=100 - yes_bid,
                  last_price=yes_bid, volume=1000, strike=strike, close_time=_future(mins))


def _provider(spot, vol=0.6):
    return lambda: (spot, vol)


def test_buys_yes_when_model_far_above_ask():
    # Spot well above strike -> fair ~100c; ask cheap at 40c -> BUY YES.
    s = CryptoFairValueStrategy(edge_cents=7, data_provider=_provider(66000))
    out = s.generate([_mkt(strike=64000, yes_bid=39, yes_ask=40)], {})
    assert len(out) == 1 and out[0].side is Side.YES and out[0].action is Action.BUY


def test_buys_no_when_model_far_below_bid():
    # Spot well below strike -> fair ~0c; bid rich at 60c -> BUY NO.
    s = CryptoFairValueStrategy(edge_cents=7, data_provider=_provider(62000))
    out = s.generate([_mkt(strike=64000, yes_bid=60, yes_ask=61)], {})
    assert len(out) == 1 and out[0].side is Side.NO
    assert out[0].limit_price_cents == 40   # 100 - yes_bid(60)


def test_no_trade_when_market_agrees():
    # Spot ~ strike -> fair ~48c; market ~48/49 -> within edge -> no trade.
    s = CryptoFairValueStrategy(edge_cents=7, data_provider=_provider(64000))
    out = s.generate([_mkt(strike=64000, yes_bid=47, yes_ask=49)], {})
    assert out == []


def test_skips_when_no_data():
    s = CryptoFairValueStrategy(data_provider=lambda: (None, None))
    assert s.generate([_mkt(64000, 40, 41)], {}) == []


def test_calibration_logger_records(tmp_path):
    from kalshi_trader.strategies.crypto import CalibrationLogger
    log = CalibrationLogger(path=str(tmp_path / "calib.jsonl"))
    s = CryptoFairValueStrategy(edge_cents=7, data_provider=_provider(66000), calib_log=log)
    s.generate([_mkt(64000, 39, 40)], {})
    lines = (tmp_path / "calib.jsonl").read_text().strip().splitlines()
    import json
    rec = json.loads(lines[0])
    assert rec["ticker"] == "KXBTC15M-X" and rec["decision"] == "BUY_YES"
    assert "model_fair_cents" in rec and "spot" in rec
