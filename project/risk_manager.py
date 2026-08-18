"""Position sizing and risk controls (Parts 14-15).

Sizing risks a fixed fraction of *current* equity at the stop distance — computed
from the real monetary loss if the stop is hit, not a naive 1%-notional rule.
"""

from __future__ import annotations

from dataclasses import dataclass


def position_size(equity: float, risk_frac: float, stop_distance_price: float,
                  usd_per_price_per_unit: float = 1.0) -> float:
    """Units such that (stop hit) loses exactly `risk_frac * equity`.

    For EUR_USD, 1 unit = 1 EUR and P/L is in USD (the quote), so a 1-price move
    is 1 USD/unit -> usd_per_price_per_unit = 1.0.
    """
    if stop_distance_price <= 0 or equity <= 0 or risk_frac <= 0:
        return 0.0
    risk_usd = equity * risk_frac
    return risk_usd / (stop_distance_price * usd_per_price_per_unit)


@dataclass
class CircuitState:
    consecutive_losses: int = 0
    day_start_equity: float = 0.0
    peak_equity: float = 0.0

    def breached(self, equity: float, rcfg) -> bool:
        if self.consecutive_losses >= rcfg.max_consecutive_losses:
            return True
        if self.peak_equity > 0 and (self.peak_equity - equity) / self.peak_equity >= rcfg.max_drawdown:
            return True
        if self.day_start_equity > 0 and (self.day_start_equity - equity) / self.day_start_equity >= rcfg.max_daily_loss:
            return True
        return False
