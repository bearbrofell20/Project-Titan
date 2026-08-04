"""A simple mispricing / mean-reversion strategy.

The idea: if you have an independent estimate of the true probability of a market
resolving Yes, buy Yes when the market's Yes ask is comfortably *below* your
estimate (cheap) and buy No when the Yes bid is comfortably *above* it (Yes is
expensive, so No is cheap).  The ``edge_cents`` margin keeps you from trading on
noise and covers the bid/ask spread.

Fair values are supplied per-ticker.  In a real deployment these would come from
a model or an external data feed; here they are an explicit input so the logic is
fully deterministic and testable.
"""

from __future__ import annotations

from typing import Dict, List

from ..models import Action, Market, OrderIntent, OrderType, Position, Side
from .base import Strategy


class MispricingThresholdStrategy(Strategy):
    name = "threshold"

    def __init__(
        self,
        fair_values_cents: Dict[str, int],
        edge_cents: int = 5,
        quantity: int = 1,
    ):
        """
        Args:
            fair_values_cents: Estimated fair Yes price (1–99) per ticker.
            edge_cents: Minimum edge over the market price required to trade.
            quantity: Contracts to buy per signal.
        """
        if edge_cents < 0:
            raise ValueError("edge_cents must be non-negative")
        if quantity <= 0:
            raise ValueError("quantity must be positive")
        self.fair_values = fair_values_cents
        self.edge_cents = edge_cents
        self.quantity = quantity

    def generate(
        self,
        markets: List[Market],
        positions: Dict[str, Position],
    ) -> List[OrderIntent]:
        intents: List[OrderIntent] = []
        for market in markets:
            if not market.is_tradable:
                continue
            fair = self.fair_values.get(market.ticker)
            if fair is None:
                continue

            # Cheap Yes: pay the ask, which sits at least edge_cents below fair.
            if market.yes_ask is not None and fair - market.yes_ask >= self.edge_cents:
                intents.append(
                    OrderIntent(
                        ticker=market.ticker,
                        action=Action.BUY,
                        side=Side.YES,
                        quantity=self.quantity,
                        order_type=OrderType.LIMIT,
                        limit_price_cents=market.yes_ask,
                        reason=(
                            f"yes_ask {market.yes_ask}c is {fair - market.yes_ask}c "
                            f"below fair {fair}c"
                        ),
                    )
                )
                continue

            # Expensive Yes -> cheap No: buy No at (100 - yes_bid).
            if market.yes_bid is not None and market.yes_bid - fair >= self.edge_cents:
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
                                f"yes_bid {market.yes_bid}c is "
                                f"{market.yes_bid - fair}c above fair {fair}c; "
                                f"buying No at {no_price}c"
                            ),
                        )
                    )
        return intents
