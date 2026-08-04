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
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .client import KalshiClient
from .config import Config
from .models import Market, OrderIntent, Position
from .risk import RiskLimits, RiskManager
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
            markets = self.client.get_markets(status="open", limit=100)

        positions_list = self._safe_positions()
        positions: Dict[str, Position] = {p.ticker: p for p in positions_list}

        intents = self.strategy.generate(markets, positions)
        self.stats.intents_generated += len(intents)

        for intent in intents:
            self._handle_intent(intent, positions_list)
        return self.stats

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
