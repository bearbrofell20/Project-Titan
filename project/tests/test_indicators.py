import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import indicators as ind


def test_ema_warmup_and_value():
    xs = [1.0] * 50
    e = ind.ema(xs, 10)
    assert e[:9] == [None] * 9          # warmup hidden
    assert abs(e[-1] - 1.0) < 1e-9      # constant series -> EMA == value


def test_ema_no_lookahead():
    xs = list(range(1, 60))
    e_full = ind.ema(xs, 10)
    e_partial = ind.ema(xs[:30], 10)
    for i in range(30):                 # truncating the future must not move the past
        assert (e_full[i] is None and e_partial[i] is None) or abs(e_full[i] - e_partial[i]) < 1e-9


def test_atr_positive():
    highs = [i + 1.5 for i in range(40)]
    lows = [i + 0.5 for i in range(40)]
    closes = [i + 1.0 for i in range(40)]
    a = ind.atr(highs, lows, closes, 14)
    assert a[13] is not None and a[-1] > 0


def test_cross_helpers():
    assert ind.crossed_up(1.0, 1.2, 1.3, 1.25)     # was below, now above
    assert not ind.crossed_up(1.3, 1.2, 1.4, 1.25)  # already above -> not a cross
    assert ind.crossed_down(1.3, 1.2, 1.1, 1.25)


if __name__ == "__main__":
    for f in [test_ema_warmup_and_value, test_ema_no_lookahead, test_atr_positive, test_cross_helpers]:
        f()
    print("PASS: indicators")
