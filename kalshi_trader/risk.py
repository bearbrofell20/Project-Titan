"""Risk controls that gate every order before it can reach the exchange.

The trading engine passes each :class:`~kalshi_trader.models.OrderIntent` through
:meth:`RiskManager.check` together with a snapshot of current positions and the
running realised loss for the day.  Any violated limit rejects the order with a
human-readable reason — nothing is submitted to Kalshi until it passes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from .config import Config
from .models import Action, OrderIntent, Position, Side


@dataclass
class RiskLimits:
    max_contracts_per_order: int
    max_position_per_market: int
    max_open_exposure_cents: int
    max_daily_loss_cents: int

    @classmethod
    def from_config(cls, config: Config) -> "RiskLimits":
        return cls(
            max_contracts_per_order=config.max_contracts_per_order,
            max_position_per_market=config.max_position_per_market,
            max_open_exposure_cents=config.max_open_exposure_cents,
            max_daily_loss_cents=config.max_daily_loss_cents,
        )


@dataclass
class RiskDecision:
    approved: bool
    reason: str = ""


class RiskManager:
    """Stateless-ish checker; all state is passed in so it is easy to test."""

    def __init__(self, limits: RiskLimits):
        self.limits = limits

    def check(
        self,
        intent: OrderIntent,
        positions: List[Position],
        realised_loss_cents_today: int = 0,
    ) -> RiskDecision:
        """Return a :class:`RiskDecision` for a proposed order."""
        # 1. Per-order size cap.
        if intent.quantity > self.limits.max_contracts_per_order:
            return RiskDecision(
                False,
                f"quantity {intent.quantity} exceeds per-order cap "
                f"{self.limits.max_contracts_per_order}",
            )

        # 2. Daily loss circuit breaker — once tripped, stop opening risk.
        if realised_loss_cents_today >= self.limits.max_daily_loss_cents:
            return RiskDecision(
                False,
                f"daily loss {realised_loss_cents_today}c has reached limit "
                f"{self.limits.max_daily_loss_cents}c; halting new orders",
            )

        by_ticker: Dict[str, Position] = {p.ticker: p for p in positions}

        # 3. Per-market position cap (only enforced when opening exposure).
        if intent.action is Action.BUY:
            current = by_ticker.get(intent.ticker)
            current_qty = abs(current.quantity) if current else 0
            projected = current_qty + intent.quantity
            if projected > self.limits.max_position_per_market:
                return RiskDecision(
                    False,
                    f"position in {intent.ticker} would reach {projected}, over cap "
                    f"{self.limits.max_position_per_market}",
                )

            # 4. Aggregate open-exposure cap across all markets.
            price = intent.limit_price_cents or 99  # market orders: assume worst
            added_exposure = intent.quantity * price
            existing_exposure = sum(p.exposure_cents for p in positions)
            if existing_exposure + added_exposure > self.limits.max_open_exposure_cents:
                return RiskDecision(
                    False,
                    f"open exposure would reach "
                    f"{existing_exposure + added_exposure}c, over cap "
                    f"{self.limits.max_open_exposure_cents}c",
                )

        return RiskDecision(True, "ok")


# ---------------------------------------------------------------------------
# Cash-out ("take any positive") helpers
# ---------------------------------------------------------------------------


def cash_out_pnl_cents(position, market):
    """Cents you'd realise by closing `position` now, or None if not quotable.

    A long-Yes position is closed by selling Yes at the Yes bid; a long-No
    position by selling No at the No bid. P/L = (sell price - avg cost) * qty.
    """
    if position.quantity > 0:  # long Yes
        if market.yes_bid is None:
            return None
        return (market.yes_bid - position.avg_price_cents) * position.quantity
    if position.quantity < 0:  # long No
        if market.no_bid is None:
            return None
        return (market.no_bid - position.avg_price_cents) * abs(position.quantity)
    return None


def should_cash_out(position, market):
    """True when the position can be closed right now for a positive P/L."""
    pnl = cash_out_pnl_cents(position, market)
    return pnl is not None and pnl > 0
