"""Central configuration for the EUR/USD M15 day-trading research system.

All knobs live here as typed dataclasses. Credentials come only from the
environment; the live environment must be selected explicitly and never by
accident.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List, Optional

PIP = 0.0001  # EUR/USD pip size (default)


def pip_size(instrument: str) -> float:
    """Pip size by instrument: 0.01 for JPY quote pairs, else 0.0001."""
    return 0.01 if instrument.endswith("JPY") else 0.0001


# --------------------------------------------------------------------------- #
# OANDA
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class OandaConfig:
    api_key: Optional[str] = field(default_factory=lambda: os.getenv("OANDA_API_KEY"))
    account_id: Optional[str] = field(default_factory=lambda: os.getenv("OANDA_ACCOUNT_ID"))
    environment: str = field(default_factory=lambda: os.getenv("OANDA_ENVIRONMENT", "practice"))

    @property
    def base_url(self) -> str:
        # 'live' must be an explicit, deliberate choice.
        if self.environment == "live":
            return "https://api-fxtrade.oanda.com"
        return "https://api-fxpractice.oanda.com"

    def assert_paper(self) -> None:
        if self.environment != "practice":
            raise RuntimeError(
                f"Refusing to run: OANDA_ENVIRONMENT={self.environment!r}, expected 'practice'. "
                "Set it to 'live' deliberately only when you truly intend live trading."
            )


# --------------------------------------------------------------------------- #
# Strategy / baseline (Part 5) — DO NOT tune before diagnosing the baseline.
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class StrategyConfig:
    instrument: str = "EUR_USD"
    entry_tf: str = "M15"
    regime_tf: str = "H4"
    entry_style: str = "cross"  # "cross" (baseline), "pullback", or "ema_trend"
    htf_ema: int = 200          # H4 trend filter
    entry_ema: int = 20         # M15 signal EMA
    fast_ema: int = 20          # ema_trend fast/slow crossover (self-contained trend)
    slow_ema: int = 60
    atr_period: int = 14
    stop_atr_mult: float = 1.5  # initial stop distance
    trail_atr_mult: float = 1.5 # ATR trailing distance (0 disables)
    # exits / management
    breakeven_at_r: float = 0.0     # move stop to entry after +Nr (0 disables)
    target_r: float = 0.0           # fixed R target (0 = no fixed target, ride trail)
    max_hold_bars: int = 0          # time stop in M15 bars (0 disables)
    # day-trading constraints (Part 12) — flat before this UTC hour boundary
    overnight_cutoff_hour_utc: Optional[int] = 20  # close positions at/after 20:00 UTC
    # session filter (Part 11): allowed UTC entry hours, empty = all
    sessions_utc: List[int] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Risk (Parts 14–15)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class RiskConfig:
    risk_per_trade: float = 0.01     # 1% of equity at the stop
    max_open_trades: int = 1
    max_daily_loss: float = 0.02     # 2% of day-start equity
    max_drawdown: float = 0.15       # 15% of peak equity -> halt new entries
    max_consecutive_losses: int = 4
    max_spread_pips: float = 3.0
    starting_equity: float = 100_000.0


# --------------------------------------------------------------------------- #
# Costs (Part 13)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class CostConfig:
    # spread is taken from real per-bar bid/ask in the data; these add on top.
    slippage_pips: float = 0.3
    commission_per_100k: float = 0.0   # OANDA spread-only accounts: 0
    spread_mult: float = 1.0           # cost-stress multiplier on the bar spread


@dataclass(frozen=True)
class Config:
    oanda: OandaConfig = field(default_factory=OandaConfig)
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    cost: CostConfig = field(default_factory=CostConfig)
