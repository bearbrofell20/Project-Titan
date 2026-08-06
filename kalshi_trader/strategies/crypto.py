"""Fair-value strategy for Kalshi short-duration crypto markets (KXBTC15M).

Each tick it computes a model fair value for every active crypto strike market
(``P(BTC >= strike)`` from live spot + realized vol + minutes-to-expiry) and
trades only when the market disagrees by at least ``edge_cents``. Every
evaluation is written to a calibration log so we can later measure — honestly,
before any real money — whether the model actually beats the market.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Tuple

from .. import crypto_model
from ..models import Action, Market, OrderIntent, OrderType, Position, Side
from .base import Strategy


class CalibrationLogger:
    """Append one JSON line per market evaluation (model vs. market snapshot)."""

    def __init__(self, path: str = "trade_logs/kalshi_calibration.jsonl"):
        self.path = path
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    def record(self, market: Market, spot, vol, minutes_left, fair_cents, decision):
        row = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "ticker": market.ticker,
            "strike": market.strike,
            "close_time": market.close_time,
            "spot": spot,
            "vol_annual": vol,
            "minutes_left": round(minutes_left, 3),
            "model_fair_cents": round(fair_cents, 2),
            "yes_bid": market.yes_bid,
            "yes_ask": market.yes_ask,
            "decision": decision,
        }
        try:
            with open(self.path, "a") as fh:
                fh.write(json.dumps(row) + "\n")
        except Exception:
            pass


# Provider returns (spot, vol_annual); default hits the live public feeds.
def _live_provider() -> Tuple[Optional[float], Optional[float]]:
    return crypto_model.fetch_btc_spot(), crypto_model.fetch_realized_vol_annual()


class CryptoFairValueStrategy(Strategy):
    name = "crypto_fairvalue"

    def __init__(
        self,
        edge_cents: int = 7,
        quantity: int = 1,
        data_provider: Optional[Callable[[], Tuple[Optional[float], Optional[float]]]] = None,
        calib_log: Optional[CalibrationLogger] = None,
    ):
        self.edge = edge_cents
        self.quantity = quantity
        self.data_provider = data_provider or _live_provider
        self.calib_log = calib_log

    def generate(self, markets: List[Market], positions: Dict[str, Position]) -> List[OrderIntent]:
        spot, vol = self.data_provider()
        if not spot or not vol:
            return []

        intents: List[OrderIntent] = []
        for m in markets:
            if m.strike is None or not m.close_time or not m.is_tradable:
                continue
            mins = crypto_model.minutes_left(m.close_time)
            if mins <= 0:
                continue
            fair = crypto_model.fair_value_cents(spot, m.strike, mins, vol)

            decision, intent = None, None
            if m.yes_ask is not None and fair - m.yes_ask >= self.edge and 1 <= m.yes_ask <= 99:
                decision = "BUY_YES"
                intent = OrderIntent(
                    ticker=m.ticker, action=Action.BUY, side=Side.YES,
                    quantity=self.quantity, order_type=OrderType.LIMIT,
                    limit_price_cents=m.yes_ask,
                    reason=f"fair {fair:.1f}c vs yes_ask {m.yes_ask}c",
                )
            elif m.yes_bid is not None and m.yes_bid - fair >= self.edge:
                no_price = 100 - m.yes_bid
                if 1 <= no_price <= 99:
                    decision = "BUY_NO"
                    intent = OrderIntent(
                        ticker=m.ticker, action=Action.BUY, side=Side.NO,
                        quantity=self.quantity, order_type=OrderType.LIMIT,
                        limit_price_cents=no_price,
                        reason=f"fair {fair:.1f}c vs yes_bid {m.yes_bid}c -> No {no_price}c",
                    )

            if self.calib_log:
                self.calib_log.record(m, spot, vol, mins, fair, decision)
            if intent:
                intents.append(intent)
        return intents
