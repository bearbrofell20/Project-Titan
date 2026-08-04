"""Command-line interface for the Kalshi auto trader.

Examples::

    # Show account balance (needs credentials)
    python -m kalshi_trader balance

    # List a few open markets
    python -m kalshi_trader markets --limit 10

    # Dry-run the momentum strategy for 5 ticks (no credentials needed)
    python -m kalshi_trader run --strategy momentum --max-ticks 5

    # Live trading (asks for confirmation, needs credentials)
    python -m kalshi_trader run --strategy threshold --live
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from typing import Dict, List, Optional

from .client import KalshiClient
from .config import Config
from .engine import TradingEngine
from .strategies import REGISTRY


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )


def _build_strategy(name: str, fair_values: Optional[Dict[str, int]]):
    if name == "threshold":
        from .strategies.threshold import MispricingThresholdStrategy

        return MispricingThresholdStrategy(fair_values_cents=fair_values or {})
    if name == "momentum":
        from .strategies.momentum import MovingAverageCrossStrategy

        return MovingAverageCrossStrategy()
    raise SystemExit(f"unknown strategy {name!r}; choices: {sorted(REGISTRY)}")


def _load_fair_values(path: Optional[str]) -> Optional[Dict[str, int]]:
    if not path:
        return None
    with open(path) as fh:
        raw = json.load(fh)
    # Keys starting with "_" are treated as comments/metadata and ignored.
    return {str(k): int(v) for k, v in raw.items() if not str(k).startswith("_")}


def cmd_markets(args, config: Config) -> int:
    client = KalshiClient(config)
    markets = client.get_markets(limit=args.limit, status=args.status)
    for m in markets:
        print(
            f"{m.ticker:<28} yes_bid={_c(m.yes_bid)} yes_ask={_c(m.yes_ask)} "
            f"last={_c(m.last_price)} vol={m.volume}  {m.title[:40]}"
        )
    print(f"\n{len(markets)} market(s).")
    return 0


def cmd_balance(args, config: Config) -> int:
    config.require_credentials()
    client = KalshiClient(config)
    cents = client.get_balance_cents()
    print(f"Balance: ${cents / 100:,.2f} ({cents}c)  [{config.environment}]")
    return 0


def cmd_positions(args, config: Config) -> int:
    config.require_credentials()
    client = KalshiClient(config)
    positions = client.get_positions()
    if not positions:
        print("No open positions.")
        return 0
    for p in positions:
        print(
            f"{p.ticker:<28} qty={p.quantity:>5} avg={p.avg_price_cents}c "
            f"exposure=${p.exposure_cents / 100:,.2f}"
        )
    return 0


def cmd_run(args, config: Config) -> int:
    if args.live:
        config.dry_run = False
    if not config.dry_run:
        config.require_credentials()
        confirm = input(
            f"About to trade LIVE on '{config.environment}' with real orders. "
            f"Type 'TRADE' to continue: "
        )
        if confirm.strip() != "TRADE":
            print("Aborted.")
            return 1

    strategy = _build_strategy(args.strategy, _load_fair_values(args.fair_values))
    client = KalshiClient(config)
    engine = TradingEngine(config, client, strategy)
    stats = engine.run_forever(max_ticks=args.max_ticks)

    print("\n=== run summary ===")
    print(f"ticks:              {stats.ticks}")
    print(f"intents generated:  {stats.intents_generated}")
    print(f"orders approved:    {stats.orders_approved}")
    print(f"orders rejected:    {stats.orders_rejected}")
    print(f"orders submitted:   {stats.orders_submitted}")
    print(f"errors:             {stats.errors}")
    if config.dry_run and stats.dry_run_orders:
        print("\nwould-be orders:")
        for i in stats.dry_run_orders:
            price = f"@{i.limit_price_cents}c" if i.limit_price_cents else "@mkt"
            print(f"  {i.action.value} {i.quantity} {i.side.value} {i.ticker} {price}")
    return 0


def _c(v: Optional[int]) -> str:
    return "  - " if v is None else f"{v:>3}c"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="kalshi_trader", description="Project Titan — Kalshi auto trader"
    )
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument(
        "--env", choices=["demo", "prod"], help="override KALSHI_ENV"
    )
    sub = p.add_subparsers(dest="command", required=True)

    m = sub.add_parser("markets", help="list open markets")
    m.add_argument("--limit", type=int, default=20)
    m.add_argument("--status", default="open")
    m.set_defaults(func=cmd_markets)

    b = sub.add_parser("balance", help="show account balance")
    b.set_defaults(func=cmd_balance)

    pos = sub.add_parser("positions", help="show open positions")
    pos.set_defaults(func=cmd_positions)

    r = sub.add_parser("run", help="run the trading engine")
    r.add_argument("--strategy", choices=sorted(REGISTRY), default="threshold")
    r.add_argument(
        "--fair-values",
        help="path to a JSON file mapping ticker -> fair Yes price in cents "
        "(threshold strategy)",
    )
    r.add_argument(
        "--max-ticks", type=int, default=None, help="stop after N ticks"
    )
    r.add_argument(
        "--live",
        action="store_true",
        help="submit REAL orders (default is dry-run)",
    )
    r.set_defaults(func=cmd_run)
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    _setup_logging(getattr(args, "verbose", False))
    config = Config.from_env()
    if getattr(args, "env", None):
        config.environment = args.env
        config.__post_init__()  # refresh derived base_url
    return args.func(args, config)


if __name__ == "__main__":
    sys.exit(main())
