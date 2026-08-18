import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import data_manager as dm
from config import Config
from strategy import build_signals
from backtester import simulate

DATA = os.getenv("EURUSD_M15", os.path.join(os.path.dirname(__file__), "..", "..",
                                            "market_data", "EUR_USD_M15.json"))


def _trades(n_bars=12000):
    candles = dm.load_candles(DATA)[:n_bars]
    m15 = dm.to_bars(candles, "M15")
    h4 = dm.resample_h4(m15)
    sig = build_signals(m15, h4, Config().strategy)
    return simulate(m15, sig, Config().strategy, Config().risk, Config().cost)


def test_runs_and_shapes():
    t = _trades()
    assert len(t) > 20
    for tr in t[:50]:
        assert tr.exit_ts >= tr.entry_ts          # no time travel
        assert tr.direction in (1, -1)
        assert tr.risk_usd > 0
        assert abs(tr.r_multiple - tr.pnl_usd / tr.risk_usd) < 1e-6


def test_one_position_at_a_time():
    t = _trades()
    for a, b in zip(t, t[1:]):
        assert b.entry_ts >= a.exit_ts            # never overlapping positions


if __name__ == "__main__":
    test_runs_and_shapes(); test_one_position_at_a_time()
    print("PASS: backtester")
