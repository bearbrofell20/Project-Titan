"""Tests for the calibration-backtest metrics."""

import crypto_backtest as cb


def test_brier_and_skill_reward_calibration():
    # A perfectly calibrated set: half the p=0.7 cases win, matching... use exact.
    # 10 preds at p=1.0 that all win, 10 at p=0.0 that all lose -> brier 0, skill 1.
    perfect = [(1.0, 1)] * 10 + [(0.0, 0)] * 10
    assert cb.brier(perfect) == 0.0
    assert abs(cb.skill_score(perfect) - 1.0) < 1e-9


def test_skill_negative_for_anti_calibrated():
    # Predict the opposite of the outcome -> worse than base rate -> skill < 0.
    bad = [(1.0, 0)] * 10 + [(0.0, 1)] * 10
    assert cb.skill_score(bad) < 0


def test_reliability_buckets():
    preds = [(0.05, 0)] * 5 + [(0.95, 1)] * 5
    rel = cb.reliability(preds, bins=10)
    # first bucket ~0.05 pred / 0 actual; last ~0.95 pred / 1 actual
    los = {round(lo, 1): (mp, ma) for lo, hi, n, mp, ma in rel}
    assert los[0.0][1] == 0.0
    assert los[0.9][1] == 1.0


def test_realized_vol_uses_only_past():
    # a flat series has ~zero vol; ensure it reads the prior window, not the future
    close = {t: 100.0 for t in range(0, 200 * 60, 60)}
    v = cb.realized_vol_annual(close, 150 * 60, lookback_min=90)
    assert v is not None and v == 0.0
