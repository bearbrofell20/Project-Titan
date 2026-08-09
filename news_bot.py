#!/usr/bin/env python3
"""Titan news bot — scans world/market news every 30 minutes, 24/7.

Writes ``trade_logs/news_feed.json`` (latest classified headlines + overall
risk posture) which the dashboard displays and the trade bot can read as an
event-risk filter. Stop it by creating ``KILL_SWITCH_NEWS.txt``.

    python news_bot.py          # loop forever, refresh every NEWS_INTERVAL sec

Config (env): NEWS_INTERVAL (default 1800), OANDA_LOG_DIR (shared log dir).
"""

import logging
import os
import time
from pathlib import Path

import news

LOG_DIR = Path(os.getenv("OANDA_LOG_DIR", "trade_logs"))
FEED_PATH = LOG_DIR / "news_feed.json"
KILL = "KILL_SWITCH_NEWS.txt"
INTERVAL = int(os.getenv("NEWS_INTERVAL", "1800"))  # 30 minutes


def scan_once() -> dict:
    state = news.NewsScanner().scan()
    news.write_feed(state, FEED_PATH)
    return state


def main():
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [NEWS] %(message)s", datefmt="%H:%M:%S")
    if os.path.exists(KILL):
        os.remove(KILL)
    logging.info("news bot online — scanning every %ds (%d feeds)", INTERVAL, len(news.FEEDS))
    while True:
        if os.path.exists(KILL):
            logging.info("kill switch present — stopping")
            break
        try:
            s = scan_once()
            r = s["risk"]
            logging.info("scanned %d headlines | risk=%s/%s | high-impact=%d | ccy=%s",
                         s["count"], r["level"], r["posture"], r["high_impact"], r["currencies"])
        except Exception as exc:
            logging.error("scan failed (continuing): %s", exc)
        for _ in range(INTERVAL):
            if os.path.exists(KILL):
                break
            time.sleep(1)
    logging.info("news bot stopped")


if __name__ == "__main__":
    main()
