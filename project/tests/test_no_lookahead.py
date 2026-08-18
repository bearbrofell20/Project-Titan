"""Part 4 (NON-NEGOTIABLE): future-data contamination test.

Procedure: generate signals on the real dataset; then mutate FUTURE candles and
regenerate; assert that no EARLIER signal changed. If an earlier signal reacts to
a future bar, the pipeline leaks look-ahead and every result is invalid.
"""

import copy
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import data_manager as dm
from config import Config
from strategy import build_signals

DATA = os.getenv("EURUSD_M15", os.path.join(os.path.dirname(__file__), "..", "..",
                                            "market_data", "EUR_USD_M15.json"))


def _signals(candles):
    m15 = dm.to_bars(candles, "M15")
    h4 = dm.resample_h4(m15)
    return build_signals(m15, h4, Config().strategy).direction


def test_no_future_leak():
    candles = dm.load_candles(DATA)[:8000]
    base = _signals(candles)
    cut = 5000  # mutate everything AFTER this bar

    mutated = copy.deepcopy(candles)
    for c in mutated[cut + 1:]:
        for side in ("bid", "mid", "ask"):
            for k in "ohlc":
                c[side][k] = float(c[side][k]) * 1.05  # shove the future 5% up
    after = _signals(mutated)

    # every signal at or before `cut` must be identical
    changed = [i for i in range(cut + 1) if base[i] != after[i]]
    assert not changed, f"LOOK-AHEAD LEAK: {len(changed)} earlier signals changed, e.g. {changed[:5]}"


if __name__ == "__main__":
    test_no_future_leak()
    print("PASS: no look-ahead contamination (earlier signals unchanged when future mutated)")
