"""Pluggable trading strategies.

A strategy consumes market state and returns zero or more
:class:`~kalshi_trader.models.OrderIntent` objects.  Register new strategies in
:data:`REGISTRY` so the CLI can select them by name.
"""

from __future__ import annotations

from typing import Dict, Type

from .base import Strategy
from .momentum import MovingAverageCrossStrategy
from .threshold import MispricingThresholdStrategy

REGISTRY: Dict[str, Type[Strategy]] = {
    "threshold": MispricingThresholdStrategy,
    "momentum": MovingAverageCrossStrategy,
}

__all__ = [
    "Strategy",
    "MispricingThresholdStrategy",
    "MovingAverageCrossStrategy",
    "REGISTRY",
]
