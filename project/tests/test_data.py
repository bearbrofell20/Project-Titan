import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import data_manager as dm

DATA = os.getenv("EURUSD_M15", os.path.join(os.path.dirname(__file__), "..", "..",
                                            "market_data", "EUR_USD_M15.json"))


def test_load_and_validate_clean():
    candles = dm.load_candles(DATA)
    assert len(candles) > 10000
    rep = dm.validate(candles, dm.TF_SECONDS["M15"])
    assert rep["duplicates"] == 0 and rep["malformed"] == 0


def test_h4_resample_completion_times_monotonic():
    m15 = dm.to_bars(dm.load_candles(DATA)[:4000], "M15")
    h4 = dm.resample_h4(m15)
    assert h4, "no H4 bars produced"
    for a, b in zip(h4, h4[1:]):
        assert b.ts > a.ts                    # buckets ordered
        assert b.end_ts == b.ts + 4 * 3600    # completion time is open + 4h
    # each H4 completes no earlier than its own open
    assert all(bar.end_ts > bar.ts for bar in h4)


if __name__ == "__main__":
    test_load_and_validate_clean(); test_h4_resample_completion_times_monotonic()
    print("PASS: data")
