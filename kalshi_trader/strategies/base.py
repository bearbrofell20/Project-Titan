"""Strategy interface.

Strategies are intentionally pure: given the current market snapshot and the
positions we already hold, they return a list of desired trades.  They never talk
to the network or place orders themselves — the engine does that after risk
checks — which keeps them trivial to unit-test.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, List

from ..models import Market, OrderIntent, Position


class Strategy(ABC):
    """Base class for all trading strategies."""

    #: Human-friendly name, overridden by subclasses.
    name: str = "base"

    @abstractmethod
    def generate(
        self,
        markets: List[Market],
        positions: Dict[str, Position],
    ) -> List[OrderIntent]:
        """Return desired order intents given current state.

        Args:
            markets: The markets under consideration this tick.
            positions: Current positions keyed by ticker.
        """
        raise NotImplementedError
