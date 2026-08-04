"""A moving-average-crossover momentum strategy.

For each market we keep a rolling history of the last traded Yes price and compare
a short moving average against a long one:

* short crosses **above** long  -> upward momentum -> buy Yes
* short crosses **below** long  -> downward momentum -> buy No

Only the *crossover* (a change of regime) triggers a trade, so a steady trend
produces one entry rather than a trade every tick.  History is fed in via
:meth:`observe`, which the engine calls once per poll, keeping the strategy pure
and deterministic for tests.
"""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Deque, Dict, List, Optional

from ..models import Action, Market, OrderIntent, OrderType, Position, Side
from .base import Strategy


class MovingAverageCrossStrategy(Strategy):
    name = "momentum"

    def __init__(
        self,
        short_window: int = 3,
        long_window: int = 8,
        quantity: int = 1,
    ):
        if short_window < 1 or long_window < 1:
            raise ValueError("windows must be >= 1")
        if short_window >= long_window:
            raise ValueError("short_window must be < long_window")
        self.short_window = short_window
        self.long_window = long_window
        self.quantity = quantity
        self._history: Dict[str, Deque[int]] = defaultdict(
            lambda: deque(maxlen=long_window)
        )
        # Last observed sign of (short - long); used to detect crossovers.
        self._last_sign: Dict[str, int] = {}

    def observe(self, market: Market) -> None:
        """Record the latest price for a market."""
        if market.last_price is not None:
            self._history[market.ticker].append(market.last_price)

    @staticmethod
    def _avg(values, window: int) -> Optional[float]:
        if len(values) < window:
            return None
        return sum(list(values)[-window:]) / window

    def generate(
        self,
        markets: List[Market],
        positions: Dict[str, Position],
    ) -> List[OrderIntent]:
        intents: List[OrderIntent] = []
        for market in markets:
            self.observe(market)
            if not market.is_tradable:
                continue

            hist = self._history[market.ticker]
            short = self._avg(hist, self.short_window)
            long = self._avg(hist, self.long_window)
            if short is None or long is None:
                continue

            sign = 1 if short > long else (-1 if short < long else 0)
            prev = self._last_sign.get(market.ticker, 0)
            self._last_sign[market.ticker] = sign

            # Only act on a genuine regime change.
            if sign == 0 or sign == prev:
                continue

            if sign > 0 and market.yes_ask is not None:
                intents.append(
                    OrderIntent(
                        ticker=market.ticker,
                        action=Action.BUY,
                        side=Side.YES,
                        quantity=self.quantity,
                        order_type=OrderType.LIMIT,
                        limit_price_cents=market.yes_ask,
                        reason=(
                            f"MA{self.short_window} {short:.1f} crossed above "
                            f"MA{self.long_window} {long:.1f}"
                        ),
                    )
                )
            elif sign < 0 and market.yes_bid is not None:
                no_price = 100 - market.yes_bid
                if 1 <= no_price <= 99:
                    intents.append(
                        OrderIntent(
                            ticker=market.ticker,
                            action=Action.BUY,
                            side=Side.NO,
                            quantity=self.quantity,
                            order_type=OrderType.LIMIT,
                            limit_price_cents=no_price,
                            reason=(
                                f"MA{self.short_window} {short:.1f} crossed below "
                                f"MA{self.long_window} {long:.1f}"
                            ),
                        )
                    )
        return intents
