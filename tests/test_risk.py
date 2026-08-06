from kalshi_trader.models import Action, OrderIntent, Position, Side
from kalshi_trader.risk import RiskLimits, RiskManager


def _intent(qty=1, price=50, ticker="X"):
    return OrderIntent(
        ticker=ticker,
        action=Action.BUY,
        side=Side.YES,
        quantity=qty,
        limit_price_cents=price,
    )


def _mgr(**over):
    limits = RiskLimits(
        max_contracts_per_order=over.get("max_contracts_per_order", 10),
        max_position_per_market=over.get("max_position_per_market", 50),
        max_open_exposure_cents=over.get("max_open_exposure_cents", 100_00),
        max_daily_loss_cents=over.get("max_daily_loss_cents", 50_00),
    )
    return RiskManager(limits)


def test_approves_normal_order():
    assert _mgr().check(_intent(), []).approved


def test_rejects_oversize_order():
    d = _mgr(max_contracts_per_order=5).check(_intent(qty=6), [])
    assert not d.approved and "per-order" in d.reason


def test_rejects_when_position_cap_exceeded():
    positions = [Position(ticker="X", quantity=48, avg_price_cents=50)]
    d = _mgr(max_position_per_market=50).check(_intent(qty=5), positions)
    assert not d.approved and "position" in d.reason


def test_rejects_when_exposure_cap_exceeded():
    d = _mgr(max_open_exposure_cents=100).check(_intent(qty=3, price=50), [])
    # 3 * 50 = 150c > 100c cap
    assert not d.approved and "exposure" in d.reason


def test_daily_loss_circuit_breaker():
    d = _mgr(max_daily_loss_cents=500).check(
        _intent(), [], realised_loss_cents_today=500
    )
    assert not d.approved and "daily loss" in d.reason


def test_exposure_counts_existing_positions():
    positions = [Position(ticker="Y", quantity=1, avg_price_cents=90)]
    # existing 90c + new 1*50 = 140c > 120c cap
    d = _mgr(max_open_exposure_cents=120).check(_intent(qty=1, price=50), positions)
    assert not d.approved


# --- cash-out ("take any positive") -----------------------------------------
from kalshi_trader.models import Market as _Market
from kalshi_trader.risk import cash_out_pnl_cents, should_cash_out


def _mkt(yes_bid=None, no_bid=None):
    return _Market(ticker="X", title="X", status="active", yes_bid=yes_bid,
                   yes_ask=None, no_bid=no_bid, no_ask=None, last_price=None)


def test_cash_out_long_yes_profit():
    p = Position(ticker="X", quantity=10, avg_price_cents=40)
    assert cash_out_pnl_cents(p, _mkt(yes_bid=55)) == (55 - 40) * 10
    assert should_cash_out(p, _mkt(yes_bid=55)) is True


def test_cash_out_long_yes_not_profitable():
    p = Position(ticker="X", quantity=10, avg_price_cents=40)
    assert should_cash_out(p, _mkt(yes_bid=40)) is False   # flat, not positive
    assert should_cash_out(p, _mkt(yes_bid=30)) is False   # loss


def test_cash_out_long_no_profit():
    p = Position(ticker="X", quantity=-8, avg_price_cents=45)
    assert cash_out_pnl_cents(p, _mkt(no_bid=60)) == (60 - 45) * 8
    assert should_cash_out(p, _mkt(no_bid=60)) is True


def test_cash_out_none_when_unquoted():
    p = Position(ticker="X", quantity=10, avg_price_cents=40)
    assert cash_out_pnl_cents(p, _mkt(yes_bid=None)) is None
    assert should_cash_out(p, _mkt(yes_bid=None)) is False
