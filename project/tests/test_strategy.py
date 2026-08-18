import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import dataclasses as dc
import data_manager as dm
from config import Config
from strategy import build_signals

DATA = os.getenv("EURUSD_M15", os.path.join(os.path.dirname(__file__), "..", "..",
                                            "market_data", "EUR_USD_M15.json"))


def _sig(cfg):
    m15 = dm.to_bars(dm.load_candles(DATA)[:12000], "M15")
    h4 = dm.resample_h4(m15)
    return build_signals(m15, h4, cfg.strategy), m15


def test_signals_respect_regime():
    cfg = Config()
    sig, m15 = _sig(cfg)
    longs = [i for i, d in enumerate(sig.direction) if d == 1]
    # every long must be in an up-regime (H4 close above its 200-EMA) at that bar
    for i in longs[:200]:
        assert sig.h4_close_at[i] is not None and sig.h4_close_at[i] > sig.h4_ema_at[i]


def test_pullback_differs_from_cross():
    base = Config()
    cross, _ = _sig(base)
    pb_cfg = dc.replace(base, strategy=dc.replace(base.strategy, entry_style="pullback"))
    pull, _ = _sig(pb_cfg)
    assert cross.direction != pull.direction   # genuinely different entry logic


if __name__ == "__main__":
    test_signals_respect_regime(); test_pullback_differs_from_cross()
    print("PASS: strategy")
