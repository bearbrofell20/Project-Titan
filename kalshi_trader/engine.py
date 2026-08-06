"""The trading engine — the loop that ties data, strategy, risk, and execution.

Each tick the engine:

1. pulls the latest markets and current positions,
2. asks the strategy for desired :class:`OrderIntent` objects,
3. runs each intent through the :class:`RiskManager`, and
4. either logs it (dry-run) or submits it to Kalshi (live).

Dry-run is the default.  Live trading requires ``config.dry_run = False``, which
the CLI only sets behind an explicit ``--live`` flag and a typed confirmation.
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .client import KalshiClient
from .config import Config
from .models import Action, Market, OrderIntent, OrderType, Position, Side
from .risk import RiskLimits, RiskManager, cash_out_pnl_cents, should_cash_out
from .strategies.base import Strategy

log = logging.getLogger("kalshi_trader")


@dataclass
class EngineStats:
    ticks: int = 0
    intents_generated: int = 0
    orders_approved: int = 0
    orders_rejected: int = 0
    orders_submitted: int = 0
    errors: int = 0
    dry_run_orders: List[OrderIntent] = field(default_factory=list)


class TradingEngine:
    def __init__(
        self,
        config: Config,
        client: KalshiClient,
        strategy: Strategy,
        risk_manager: Optional[RiskManager] = None,
    ):
        self.config = config
        self.client = client
        self.strategy = strategy
        self.risk = risk_manager or RiskManager(RiskLimits.from_config(config))
        self.stats = EngineStats()

    # -- one iteration -----------------------------------------------------
    def run_once(self, markets: Optional[List[Market]] = None) -> EngineStats:
        """Run a single tick.  Markets may be injected (used by tests/backtests)."""
        self.stats.ticks += 1

        if markets is None:
            markets = self.client.get_markets(
                status="open", limit=100, series_ticker=self.config.market_series,
            )

        positions_list = self._safe_positions()
        positions: Dict[str, Position] = {p.ticker: p for p in positions_list}
        market_by_ticker: Dict[str, Market] = {m.ticker: m for m in markets}

        # Rule: cash out any position we can close for a profit (always allowed,
        # even below the cash floor — closing raises cash).
        if self.config.cash_out_positive:
            self._cash_out_positive(positions_list, market_by_ticker)

        # Always evaluate the strategy (this also records calibration), so we
        # observe the model even when we can't trade...
        intents = self.strategy.generate(markets, positions)
        self.stats.intents_generated += len(intents)

        # ...but the cash floor gates order SUBMISSION: no new positions below it.
        if not self._cash_above_floor():
            if intents:
                log.info("cash floor: available < $%.2f — %d signal(s) not submitted",
                         self.config.min_cash_cents / 100, len(intents))
            return self.stats

        for intent in intents:
            self._handle_intent(intent, positions_list)
        return self.stats

    def _cash_above_floor(self) -> bool:
        """True if available cash is at/above the floor. Fails safe (blocks) if
        the balance can't be confirmed."""
        if self.config.dry_run and not self.config.api_key_id:
            return True  # offline dry-run: nothing real happens, allow entries
        try:
            return self.client.get_balance_cents() >= self.config.min_cash_cents
        except Exception as exc:
            log.warning("balance check failed, blocking new entries: %s", exc)
            return False

    def _cash_out_positive(self, positions: List[Position], markets: Dict[str, Market]) -> None:
        """Close any position that can currently be sold for a profit."""
        for p in positions:
            m = markets.get(p.ticker)
            if m is None or not should_cash_out(p, m):
                continue
            intent = _close_intent(p, m)
            if intent is None:
                continue
            log.info("CASH-OUT %s (+%dc)", p.ticker, cash_out_pnl_cents(p, m))
            self._handle_intent(intent, positions)

    def _safe_positions(self) -> List[Position]:
        """Fetch positions, tolerating dry-run runs without credentials."""
        if self.config.dry_run and not self.config.api_key_id:
            return []
        try:
            return self.client.get_positions()
        except Exception as exc:  # network / auth issues shouldn't crash the loop
            log.warning("could not fetch positions: %s", exc)
            self.stats.errors += 1
            return []

    def _handle_intent(self, intent: OrderIntent, positions: List[Position]) -> None:
        decision = self.risk.check(intent, positions)
        if not decision.approved:
            self.stats.orders_rejected += 1
            log.info("REJECTED %s | %s", _fmt(intent), decision.reason)
            return

        self.stats.orders_approved += 1
        if self.config.dry_run:
            self.stats.dry_run_orders.append(intent)
            log.info("DRY-RUN would submit %s | %s", _fmt(intent), intent.reason)
            return

        try:
            client_order_id = str(uuid.uuid4())
            self.client.place_order(intent, client_order_id)
            self.stats.orders_submitted += 1
            log.info("SUBMITTED %s | %s", _fmt(intent), intent.reason)
        except Exception as exc:
            self.stats.errors += 1
            log.error("failed to submit %s: %s", _fmt(intent), exc)

    # -- long-running loop -------------------------------------------------
    def run_forever(self, max_ticks: Optional[int] = None) -> EngineStats:
        mode = "DRY-RUN" if self.config.dry_run else "LIVE"
        log.info(
            "starting engine [%s] strategy=%s env=%s interval=%ss",
            mode,
            self.strategy.name,
            self.config.environment,
            self.config.poll_interval_seconds,
        )
        try:
            while max_ticks is None or self.stats.ticks < max_ticks:
                if os.path.exists(self.config.kill_switch_file):
                    log.info("kill switch present — shutting down cleanly")
                    break
                try:
                    self.run_once()
                except Exception as exc:
                    self.stats.errors += 1
                    log.error("tick failed: %s", exc)
                if max_ticks is not None and self.stats.ticks >= max_ticks:
                    break
                time.sleep(self.config.poll_interval_seconds)
        except KeyboardInterrupt:
            log.info("interrupted; shutting down cleanly")
        log.info("engine stopped: %s", self.stats)
        return self.stats


def _close_intent(position: Position, market: Market) -> Optional[OrderIntent]:
    """Build the SELL order that closes `position` at the current bid."""
    if position.quantity > 0:  # long Yes -> sell Yes
        if market.yes_bid is None:
            return None
        return OrderIntent(
            ticker=position.ticker, action=Action.SELL, side=Side.YES,
            quantity=position.quantity, order_type=OrderType.LIMIT,
            limit_price_cents=market.yes_bid, reason="cash-out positive",
        )
    if position.quantity < 0:  # long No -> sell No
        if market.no_bid is None:
            return None
        return OrderIntent(
            ticker=position.ticker, action=Action.SELL, side=Side.NO,
            quantity=abs(position.quantity), order_type=OrderType.LIMIT,
            limit_price_cents=market.no_bid, reason="cash-out positive",
        )
    return None


def _fmt(intent: OrderIntent) -> str:
    price = (
        f"@{intent.limit_price_cents}c"
        if intent.limit_price_cents is not None
        else "@mkt"
    )
    return (
        f"{intent.action.value} {intent.quantity} {intent.side.value} "
        f"{intent.ticker} {price}"
    )
