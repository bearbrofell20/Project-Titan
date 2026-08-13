#!/usr/bin/env python3
"""
Run the trading bots and the unified dashboard together in one process.

    python run_all.py        # OANDA bot + dashboard on http://localhost:8080

By default this runs the OANDA forex bot plus the dashboard. Set
KALSHI_ENABLE=true (with Kalshi credentials configured) to also run the Kalshi
event-contracts bot — then both bots trade under the one dashboard.

Layout:
  * dashboard  -> background thread (serves http://localhost:8080)
  * Kalshi bot -> background thread (only if KALSHI_ENABLE is set)
  * OANDA bot  -> main thread (blocks until Ctrl-C / KILL_SWITCH.txt)

Designed as the entry point for a 24/7 service (systemd, Docker, …) — see the
"Running 24/7" section of the README.
"""

import os
import threading

import dashboard
import oanda_trader


def _enabled(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _serve_dashboard():
    try:
        dashboard.main()
    except Exception as e:  # a dashboard error must never take down the bots
        print(f"[dashboard] stopped: {e}")


def _run_kalshi():
    """Run the Kalshi event-contracts bot (opt-in, dry-run unless configured)."""
    if not _enabled("KALSHI_ENABLE"):
        return
    try:
        from kalshi_trader.client import KalshiClient
        from kalshi_trader.config import Config as KConfig
        from kalshi_trader.engine import TradingEngine
        from kalshi_trader.strategies import REGISTRY

        cfg = KConfig.from_env()
        if not (cfg.api_key_id and cfg.private_key_path):
            print("[kalshi] KALSHI_ENABLE set but credentials missing; skipping.")
            return
        strat_name = os.getenv("KALSHI_STRATEGY", "momentum")
        strategy = REGISTRY.get(strat_name, REGISTRY["momentum"])()
        engine = TradingEngine(cfg, KalshiClient(cfg), strategy)
        engine.run_forever()
    except Exception as e:
        print(f"[kalshi] stopped: {e}")


def _run_news():
    """Scan world/market news every 30 min (on by default; NEWS_ENABLE=false to skip)."""
    if os.getenv("NEWS_ENABLE", "true").strip().lower() in {"0", "false", "no", "off"}:
        return
    try:
        import news_bot
        news_bot.main()
    except Exception as e:
        print(f"[news] stopped: {e}")


def _run_events():
    """Collect news-event -> currency-reaction data (the forex news-edge experiment).
    Needs the OANDA client for live prices; on by default (EVENT_STUDY=false to skip)."""
    if os.getenv("EVENT_STUDY", "true").strip().lower() in {"0", "false", "no", "off"}:
        return
    try:
        import time
        import event_study
        import oanda_trader as ot
        token = ot._load_api_token()
        if not token:
            return
        client = ot.OandaClient(token)
        collector = event_study.EventCollector(str(ot.Config.LOG_DIR))
        while True:
            try:
                collector.poll(client)
            except Exception as e:
                print(f"[events] tick error: {e}")
            time.sleep(120)  # every 2 min: catch reaction windows
    except Exception as e:
        print(f"[events] stopped: {e}")


def main():
    threading.Thread(target=_serve_dashboard, daemon=True).start()
    threading.Thread(target=_run_news, daemon=True).start()
    threading.Thread(target=_run_events, daemon=True).start()
    if _enabled("KALSHI_ENABLE"):
        threading.Thread(target=_run_kalshi, daemon=True).start()
    # OANDA bot blocks in the trading loop until Ctrl-C / kill switch.
    oanda_trader.main()


if __name__ == "__main__":
    main()
