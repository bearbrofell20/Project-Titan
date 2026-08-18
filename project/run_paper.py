"""Paper-trading entry point (Part 27).

Per the project's own rule — "only after validation passes should the paper-trading
module be enabled" — this refuses to start, because validation returned
NO ROBUST EDGE FOUND. A frozen, validated strategy config does not exist, so there
is nothing honest to paper-trade. When (if) a candidate passes run_validation.py,
freeze its config here and remove the guard.

This is deliberate: it prevents the exact failure mode this project exists to avoid
— running an unvalidated strategy with real (even paper) stakes and mistaking
variance for edge.
"""

from __future__ import annotations

import sys

from config import Config

VALIDATED_STRATEGY = None  # set to a frozen StrategyConfig once one passes OOS


def main() -> int:
    cfg = Config()
    cfg.oanda.assert_paper()  # never live by accident
    if VALIDATED_STRATEGY is None:
        print("REFUSING TO PAPER-TRADE: no strategy has passed validation.")
        print("run_validation.py verdict: NO ROBUST EDGE FOUND on EUR/USD M15.")
        print("Freeze a validated config into VALIDATED_STRATEGY before enabling this.")
        return 1
    # (unreachable until a validated strategy exists)
    return 0


if __name__ == "__main__":
    sys.exit(main())
