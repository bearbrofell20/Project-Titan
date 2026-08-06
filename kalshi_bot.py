#!/usr/bin/env python3
"""
Standalone Kalshi crypto fair-value bot (dry-run, calibration-logging).

Runs the CryptoFairValueStrategy over the configured series (default KXBTC15M):
each tick it models P(BTC >= strike), trades only on an edge-sized disagreement,
and logs every model-vs-market observation for calibration. The $5 cash floor
and cash-out-any-positive rules apply. Dry-run stays on until deliberately
turned off — this is a real-money (prod) account.

Config comes from the environment / .env (KALSHI_* vars). Stop it by creating
KILL_SWITCH_KALSHI.txt (the dashboard Stop button does this).
"""

import logging
import os

from kalshi_trader.client import KalshiClient
from kalshi_trader.config import Config
from kalshi_trader.engine import TradingEngine
from kalshi_trader.strategies.crypto import CalibrationLogger, CryptoFairValueStrategy


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    cfg = Config.from_env()
    if not (cfg.api_key_id and cfg.private_key_path):
        logging.error("Kalshi credentials missing (KALSHI_API_KEY_ID / KALSHI_PRIVATE_KEY_PATH)")
        raise SystemExit(1)
    if not cfg.market_series:
        cfg.market_series = os.getenv("KALSHI_SERIES_TICKER", "KXBTC15M")

    edge = int(os.getenv("KALSHI_EDGE_CENTS", "7"))
    strategy = CryptoFairValueStrategy(edge_cents=edge, calib_log=CalibrationLogger())
    engine = TradingEngine(cfg, KalshiClient(cfg), strategy)

    logging.info(
        "Kalshi crypto bot | series=%s | env=%s | dry_run=%s | edge=%dc | "
        "min_cash=$%.2f | cash_out=%s",
        cfg.market_series, cfg.environment, cfg.dry_run, edge,
        cfg.min_cash_cents / 100, cfg.cash_out_positive,
    )
    # clear a stale kill switch so this run isn't stopped instantly
    if os.path.exists(cfg.kill_switch_file):
        os.remove(cfg.kill_switch_file)
    try:
        engine.run_forever()
    except KeyboardInterrupt:
        logging.info("interrupted")


if __name__ == "__main__":
    main()
