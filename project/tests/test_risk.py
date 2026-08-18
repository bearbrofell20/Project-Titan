import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from risk_manager import position_size


def test_risk_is_exactly_one_percent():
    eq, frac = 100_000.0, 0.01
    stop_dist = 0.0015  # 15 pips
    units = position_size(eq, frac, stop_dist)
    loss_at_stop = units * stop_dist   # USD lost if stop hit
    assert abs(loss_at_stop - eq * frac) < 1e-6   # exactly $1000


def test_wider_stop_smaller_size():
    a = position_size(100_000, 0.01, 0.0010)
    b = position_size(100_000, 0.01, 0.0020)
    assert b < a and abs(a / b - 2.0) < 1e-9


def test_degenerate_inputs_safe():
    assert position_size(0, 0.01, 0.001) == 0.0
    assert position_size(100_000, 0.01, 0) == 0.0


if __name__ == "__main__":
    test_risk_is_exactly_one_percent(); test_wider_stop_smaller_size(); test_degenerate_inputs_safe()
    print("PASS: risk sizing")
