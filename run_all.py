#!/usr/bin/env python3
"""
Run the OANDA bot and the dashboard together in one process.

    python run_all.py        # bot trades; dashboard on http://localhost:8080

The dashboard runs in a background thread; the trading loop runs in the main
thread. Stop with Ctrl-C, or create the kill-switch file (KILL_SWITCH.txt) to
stop just the bot. Designed to be the entry point for a 24/7 service (systemd,
Docker, etc.) — see the "Running 24/7" section of the README.
"""

import threading

import dashboard
import oanda_trader


def _serve_dashboard():
    try:
        dashboard.main()
    except Exception as e:  # never let a dashboard error take down the bot
        print(f"[dashboard] stopped: {e}")


def main():
    threading.Thread(target=_serve_dashboard, daemon=True).start()
    # Blocks in the trading loop until Ctrl-C / kill switch.
    oanda_trader.main()


if __name__ == "__main__":
    main()
