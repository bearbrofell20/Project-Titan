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
