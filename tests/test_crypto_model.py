import math
from kalshi_trader.crypto_model import fair_prob_ge, fair_value_cents


def test_deep_itm_near_one():
    assert fair_prob_ge(70000, 64000, minutes_left=10, vol_annual=0.6) > 0.99


def test_deep_otm_near_zero():
    assert fair_prob_ge(60000, 64000, minutes_left=10, vol_annual=0.6) < 0.01


def test_atm_near_half():
    p = fair_prob_ge(64000, 64000, minutes_left=15, vol_annual=0.6)
    assert 0.45 < p < 0.5   # slightly under 0.5 from the -0.5*sigma^2 drift term


def test_zero_time_is_deterministic():
    assert fair_prob_ge(64001, 64000, 0, 0.6) == 1.0
    assert fair_prob_ge(63999, 64000, 0, 0.6) == 0.0


def test_fair_value_cents_range():
    c = fair_value_cents(64000, 64000, 15, 0.6)
    assert 0 <= c <= 100


def test_more_time_more_uncertainty():
    # Same OTM strike: more time left -> higher chance of reaching it.
    near = fair_prob_ge(63950, 64000, minutes_left=1, vol_annual=0.6)
    far = fair_prob_ge(63950, 64000, minutes_left=14, vol_annual=0.6)
    assert far > near
