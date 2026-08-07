"""Expectancy and profit-factor math must be exactly right — they are the numbers
the whole go/no-go decision rests on."""

import bt
import metrics


def _t(r):
    return bt.Trade(direction="BUY", entry_time=0, entry=1.0, stop=0.99, target=1.02,
                    r_multiple=r, pips=r * 20)


def test_expectancy_and_profit_factor():
    trades = [_t(2), _t(-1), _t(-1), _t(2), _t(-1)]  # +2 -1 -1 +2 -1 = +1 net over 5
    m = metrics.summarize(trades)
    assert m["trades"] == 5
    assert abs(m["net_r"] - 1.0) < 1e-9
    assert abs(m["expectancy_r"] - 0.2) < 1e-9        # +1R / 5 trades
    assert abs(m["profit_factor"] - (4 / 3)) < 1e-9   # gross win 4 / gross loss 3
    assert abs(m["win_rate"] - 40.0) < 1e-9


def test_max_drawdown_in_r():
    # equity: +2, +1, -1... peak 3 then down to  after losses
    trades = [_t(2), _t(-3), _t(1)]  # eq: 2, -1, 0 ; peak 2 -> trough -1 => DD -3
    m = metrics.summarize(trades)
    assert abs(m["max_dd_r"] - (-3.0)) < 1e-9


def test_losing_streak():
    trades = [_t(1), _t(-1), _t(-1), _t(-1), _t(2), _t(-1)]
    m = metrics.summarize(trades)
    assert m["max_loss_streak"] == 3


def test_empty():
    m = metrics.summarize([])
    assert m["trades"] == 0
    assert m["expectancy_r"] == 0.0
