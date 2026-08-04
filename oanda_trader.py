#!/usr/bin/env python3
"""
OANDA Multi-Pair 5-Minute Momentum Scalper  (Project Titan — Forex Division)

Momentum-following strategy across many pairs on 5-minute candles.

This is the bug-fixed, integrated version of the original scalper. Behaviour that
was preserved: the RSI + trend signal logic, the poll loop, the kill switch, and
per-candle de-duplication. What changed (see README "Forex" section):

  * Position sizing is now correct. The original risked ~100x the intended
    amount because of a bad pip-cost constant; sizing now converts the pip value
    into account currency (USD) per pair, so `$RISK_PER_TRADE` means what it says.
  * JPY-pair stop/take-profit prices are rounded to the instrument's real
    precision (3 decimals) instead of 5, so those orders are no longer rejected.
  * A DRY_RUN switch logs intended orders without sending them, and a guard
    blocks the live (fxtrade) endpoint unless it is explicitly allowed.
  * Importing the module no longer has side effects (logging is set up in main).

Mode: DEMO practice endpoint by default (safe testing).
"""

import os
import json
import time
import logging
from datetime import datetime
from collections import defaultdict

import requests
from pathlib import Path

# ============================================================================
# CONFIGURATION
# ============================================================================


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class Config:
    # OANDA Setup ------------------------------------------------------------
    ACCOUNT_ID = os.getenv("OANDA_ACCOUNT_ID", "101-001-39975042-001")
    # Practice (demo) by default; the live endpoint is api-fxtrade.oanda.com.
    API_URL = os.getenv("OANDA_API_URL", "https://api-fxpractice.oanda.com")

    INSTRUMENTS = [
        "EUR_USD", "GBP_USD", "USD_JPY", "USD_CHF", "AUD_USD",
        "NZD_USD", "EUR_GBP", "EUR_JPY", "GBP_JPY", "USD_CAD",
        "USD_SEK", "USD_NOK", "USD_CNH",
    ]

    # Trading Parameters -----------------------------------------------------
    TIMEFRAME = "M5"                    # 5-minute candles
    RISK_PER_TRADE = float(os.getenv("OANDA_RISK_PER_TRADE", "10.0"))  # USD

    # Momentum Thresholds ----------------------------------------------------
    RSI_PERIOD = 14
    RSI_OVERSOLD = 30                   # dip within an uptrend -> buy
    RSI_OVERBOUGHT = 70                 # rally within a downtrend -> sell

    # Risk Management --------------------------------------------------------
    STOP_LOSS_PIPS = 20
    TAKE_PROFIT_PIPS = 40
    MAX_OPEN_TRADES = int(os.getenv("OANDA_MAX_OPEN_TRADES", "6"))
    # One position per instrument at a time (no stacking on every candle).
    ONE_POSITION_PER_INSTRUMENT = True

    # Safety -----------------------------------------------------------------
    # DRY_RUN: log intended orders, send nothing. Default False so the demo
    # endpoint can actually place practice orders (its whole purpose).
    DRY_RUN = _env_bool("OANDA_DRY_RUN", False)
    # The live endpoint is refused unless this is explicitly turned on.
    ALLOW_LIVE = _env_bool("OANDA_ALLOW_LIVE", False)

    # Operational ------------------------------------------------------------
    POLL_INTERVAL = int(os.getenv("OANDA_POLL_INTERVAL", "30"))
    KILL_SWITCH_FILE = os.getenv("OANDA_KILL_SWITCH_FILE", "KILL_SWITCH.txt")

    # Logging ----------------------------------------------------------------
    LOG_DIR = Path(os.getenv("OANDA_LOG_DIR", "trade_logs"))
    STATS_FILE = LOG_DIR / f"trades_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

    @classmethod
    def is_live_endpoint(cls) -> bool:
        return "fxtrade" in cls.API_URL and "fxpractice" not in cls.API_URL


def validate_config(api_token: str):
    """Return a list of human-readable problems; empty list == OK."""
    problems = []
    if not api_token:
        problems.append("API token is missing (OANDA_API_TOKEN or oanda_config.API_TOKEN)")
    if not Config.ACCOUNT_ID:
        problems.append("OANDA_ACCOUNT_ID is missing")
    if Config.RISK_PER_TRADE <= 0:
        problems.append("RISK_PER_TRADE must be positive")
    if Config.is_live_endpoint() and not Config.ALLOW_LIVE:
        problems.append(
            "API_URL points at the LIVE endpoint but OANDA_ALLOW_LIVE is not set. "
            "Refusing to trade real money. Set OANDA_ALLOW_LIVE=yes to override."
        )
    return problems


# ============================================================================
# LOGGER SETUP  (no side effects at import time)
# ============================================================================

logger = logging.getLogger("OandaBot")
logger.addHandler(logging.NullHandler())


def setup_logger():
    """Attach console + file handlers. Call once from main()."""
    os.makedirs(Config.LOG_DIR, exist_ok=True)
    logger.setLevel(logging.DEBUG)

    fh = logging.FileHandler(
        Config.LOG_DIR / f"bot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    )
    fh.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )
    fh.setFormatter(formatter)
    ch.setFormatter(formatter)

    logger.addHandler(fh)
    logger.addHandler(ch)
    return logger


# ============================================================================
# PRICE / PRECISION HELPERS
# ============================================================================


def pip_size(instrument: str) -> float:
    """Pip size in price terms (0.01 for JPY-quoted pairs, else 0.0001)."""
    return 0.01 if "JPY" in instrument else 0.0001


def price_decimals(instrument: str) -> int:
    """Decimal places OANDA expects for a price on this instrument."""
    return 3 if "JPY" in instrument else 5


# ============================================================================
# OANDA API CLIENT
# ============================================================================


class OandaClient:
    """Wrapper for OANDA v20 REST API."""

    def __init__(self, api_token):
        self.api_token = api_token
        self.headers = {
            "Authorization": f"Bearer {api_token}",
            "AcceptDatetimeFormat": "UNIX",
            "Content-Type": "application/json",
        }

    def get_candles(self, instrument, granularity="M5", count=100):
        """Fetch recent candles for an instrument."""
        try:
            url = f"{Config.API_URL}/v3/instruments/{instrument}/candles"
            params = {
                "granularity": granularity,
                "count": count,
                "price": "MBA",  # Mid, Bid, Ask
            }
            response = requests.get(url, headers=self.headers, params=params, timeout=10)
            response.raise_for_status()
            return response.json().get("candles", [])
        except Exception as e:
            logger.error(f"Error fetching candles for {instrument}: {e}")
            return []

    def get_price(self, instrument):
        """Latest mid close price for an instrument, or None."""
        candles = self.get_candles(instrument, count=1)
        if not candles:
            return None
        try:
            return float(candles[-1]["mid"]["c"])
        except (KeyError, ValueError):
            return None

    def get_account_details(self):
        """Fetch current account balance and margin info."""
        try:
            url = f"{Config.API_URL}/v3/accounts/{Config.ACCOUNT_ID}"
            response = requests.get(url, headers=self.headers, timeout=10)
            response.raise_for_status()
            return response.json().get("account", {})
        except Exception as e:
            logger.error(f"Error fetching account details: {e}")
            return {}

    def get_open_instruments(self):
        """Set of instruments with a currently open position."""
        try:
            url = f"{Config.API_URL}/v3/accounts/{Config.ACCOUNT_ID}/openPositions"
            response = requests.get(url, headers=self.headers, timeout=10)
            response.raise_for_status()
            positions = response.json().get("positions", [])
            return {p["instrument"] for p in positions}
        except Exception as e:
            logger.error(f"Error fetching open positions: {e}")
            return set()

    def place_order(self, instrument, units, entry_price, stop_loss_pips, take_profit_pips):
        """Place a market order with SL and TP at the correct price precision."""
        try:
            ps = pip_size(instrument)
            decimals = price_decimals(instrument)

            if units > 0:  # BUY
                sl_price = entry_price - (stop_loss_pips * ps)
                tp_price = entry_price + (take_profit_pips * ps)
            else:          # SELL
                sl_price = entry_price + (stop_loss_pips * ps)
                tp_price = entry_price - (take_profit_pips * ps)

            order_body = {
                "order": {
                    "instrument": instrument,
                    "units": str(int(units)),
                    "type": "MARKET",
                    "timeInForce": "FOK",
                    "takeProfitOnFill": {"price": f"{tp_price:.{decimals}f}"},
                    "stopLossOnFill": {"price": f"{sl_price:.{decimals}f}"},
                }
            }

            if Config.DRY_RUN:
                logger.info(
                    f"[DRY-RUN] would place {instrument} {int(units)} units @ "
                    f"~{entry_price:.{decimals}f} | SL {sl_price:.{decimals}f} | "
                    f"TP {tp_price:.{decimals}f}"
                )
                return {"dryRun": True, "sl": sl_price, "tp": tp_price}

            url = f"{Config.API_URL}/v3/accounts/{Config.ACCOUNT_ID}/orders"
            response = requests.post(url, headers=self.headers, json=order_body, timeout=10)
            response.raise_for_status()

            order_data = response.json()
            if "orderFillTransaction" in order_data:
                logger.info(
                    f"✓ ORDER FILLED: {instrument} {int(units)} units @ "
                    f"{order_data['orderFillTransaction']['price']} | "
                    f"SL: {sl_price:.{decimals}f} | TP: {tp_price:.{decimals}f}"
                )
                return order_data
            logger.warning(f"Order not filled for {instrument}: {order_data}")
            return None
        except Exception as e:
            logger.error(f"Error placing order for {instrument}: {e}")
            return None


# ============================================================================
# MOMENTUM DETECTOR   (unchanged strategy logic)
# ============================================================================


class MomentumDetector:
    """Calculate RSI and trend for momentum detection."""

    @staticmethod
    def calculate_rsi(prices, period=14):
        """RSI over the last `period` deltas (simple-average variant)."""
        if len(prices) < period + 1:
            return None

        deltas = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
        gains = [d if d > 0 else 0 for d in deltas]
        losses = [-d if d < 0 else 0 for d in deltas]

        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period

        if avg_loss == 0:
            return 100 if avg_gain > 0 else 0

        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    @staticmethod
    def detect_trend(candles, period=3):
        """Simple trend: compare last N close prices."""
        if len(candles) < period:
            return None
        closes = [float(c["mid"]["c"]) for c in candles[-period:]]
        if closes[-1] > closes[0]:
            return "UP"
        if closes[-1] < closes[0]:
            return "DOWN"
        return "FLAT"

    @staticmethod
    def get_signal(candles, instrument):
        """Combined momentum signal: RSI + trend confirmation -> 'BUY'/'SELL'/None."""
        if len(candles) < 20:
            return None

        closes = [float(c["mid"]["c"]) for c in candles]
        rsi = MomentumDetector.calculate_rsi(closes, Config.RSI_PERIOD)
        trend = MomentumDetector.detect_trend(candles, 3)
        if rsi is None or trend is None:
            return None

        if rsi < Config.RSI_OVERSOLD and trend == "UP":
            logger.debug(f"  {instrument}: RSI={rsi:.1f} (oversold) + Uptrend -> BUY")
            return "BUY"
        if rsi > Config.RSI_OVERBOUGHT and trend == "DOWN":
            logger.debug(f"  {instrument}: RSI={rsi:.1f} (overbought) + Downtrend -> SELL")
            return "SELL"
        return None


# ============================================================================
# POSITION MANAGER   (fixed sizing)
# ============================================================================


class PositionManager:
    """Size positions so each trade risks exactly RISK_PER_TRADE in USD."""

    @staticmethod
    def calculate_units(instrument, stop_loss_pips, quote_to_usd, risk_usd=None):
        """Units such that a stop-out loses ~`risk_usd`.

        risk = units * pip_size * quote_to_usd * stop_loss_pips
          -> units = risk / (pip_size * quote_to_usd * stop_loss_pips)

        `quote_to_usd` converts one unit of the pair's *quote* currency into USD
        (1.0 for XXX_USD pairs, 1/price for USD_XXX pairs, a cross rate otherwise).
        """
        if risk_usd is None:
            risk_usd = Config.RISK_PER_TRADE
        if quote_to_usd is None or quote_to_usd <= 0 or stop_loss_pips <= 0:
            return 0
        pip_value_usd_per_unit = pip_size(instrument) * quote_to_usd
        if pip_value_usd_per_unit <= 0:
            return 0
        units = risk_usd / (pip_value_usd_per_unit * stop_loss_pips)
        return int(units)


# ============================================================================
# TRADE LOGGER
# ============================================================================


class TradeLogger:
    """Log all trades for analysis."""

    def __init__(self, filepath):
        self.filepath = filepath
        self.trades = []
        os.makedirs(self.filepath.parent, exist_ok=True)

    def log_trade(self, instrument, direction, units, entry_price, sl, tp, timestamp=None):
        self.trades.append(
            {
                "timestamp": timestamp or datetime.now().isoformat(),
                "instrument": instrument,
                "direction": direction,
                "units": units,
                "entry_price": entry_price,
                "stop_loss": sl,
                "take_profit": tp,
                "risk": Config.RISK_PER_TRADE,
            }
        )
        self._save()

    def _save(self):
        try:
            with open(self.filepath, "w") as f:
                json.dump(self.trades, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving trades: {e}")

    def summary(self):
        if not self.trades:
            return "No trades logged yet."
        return f"Total trades: {len(self.trades)}"


# ============================================================================
# MAIN BOT
# ============================================================================


class OandaBot:
    """Main bot orchestrator."""

    def __init__(self, api_token):
        self.client = OandaClient(api_token)
        self.trade_logger = TradeLogger(Config.STATS_FILE)
        self.last_candle_time = defaultdict(int)
        self.running = True
        self._rate_cache = {}  # quote-currency -> USD rate, refreshed each cycle

        mode = "DRY-RUN" if Config.DRY_RUN else ("LIVE" if Config.is_live_endpoint() else "DEMO")
        logger.info("=" * 60)
        logger.info("🤖 OANDA MULTI-PAIR 5-MIN MOMENTUM BOT")
        logger.info("=" * 60)
        logger.info(f"Account: {Config.ACCOUNT_ID}")
        logger.info(f"Mode: {mode}")
        logger.info(f"Risk per trade: ${Config.RISK_PER_TRADE}")
        logger.info(f"Stop Loss: {Config.STOP_LOSS_PIPS} pips | Take Profit: {Config.TAKE_PROFIT_PIPS} pips")
        logger.info(f"Monitoring {len(Config.INSTRUMENTS)} pairs")
        logger.info(f"Kill switch: create '{Config.KILL_SWITCH_FILE}' to stop")
        logger.info("=" * 60)

    # -- helpers -----------------------------------------------------------
    def check_kill_switch(self):
        if os.path.exists(Config.KILL_SWITCH_FILE):
            logger.warning("⚠️  KILL SWITCH ACTIVATED - shutting down bot")
            self.running = False
            return True
        return False

    def quote_to_usd(self, instrument):
        """Rate to convert the pair's quote currency into USD (with caching)."""
        quote = instrument.split("_")[1]
        if quote == "USD":
            return 1.0
        if quote in self._rate_cache:
            return self._rate_cache[quote]

        rate = None
        direct = self.client.get_price(f"{quote}_USD")  # e.g. GBP_USD
        if direct:
            rate = direct
        else:
            inverse = self.client.get_price(f"USD_{quote}")  # e.g. USD_JPY
            if inverse:
                rate = 1.0 / inverse

        if rate is None:
            logger.warning(f"No USD conversion for {quote}; skipping sizing for {instrument}")
        self._rate_cache[quote] = rate
        return rate

    # -- per-pair scan -----------------------------------------------------
    def scan_pair(self, instrument, open_instruments):
        try:
            candles = self.client.get_candles(instrument, granularity="M5", count=50)
            if not candles:
                return

            latest_time = int(float(candles[-1]["time"]))
            if latest_time <= self.last_candle_time[instrument]:
                return  # no new candle yet
            self.last_candle_time[instrument] = latest_time

            signal = MomentumDetector.get_signal(candles, instrument)
            if not signal:
                return

            if Config.ONE_POSITION_PER_INSTRUMENT and instrument in open_instruments:
                logger.info(f"Skip {instrument}: position already open")
                return
            if len(open_instruments) >= Config.MAX_OPEN_TRADES:
                logger.info(f"Skip {instrument}: max open trades ({Config.MAX_OPEN_TRADES}) reached")
                return

            q2usd = self.quote_to_usd(instrument)
            units = PositionManager.calculate_units(instrument, Config.STOP_LOSS_PIPS, q2usd)
            if units <= 0:
                logger.warning(f"Skip {instrument}: computed 0 units (sizing unavailable)")
                return
            if signal == "SELL":
                units = -units

            entry_price = float(candles[-1]["mid"]["c"])
            logger.info(f"\n📊 SIGNAL: {signal} {instrument} ({units} units)")
            order = self.client.place_order(
                instrument, units, entry_price,
                Config.STOP_LOSS_PIPS, Config.TAKE_PROFIT_PIPS,
            )
            if order:
                open_instruments.add(instrument)  # avoid re-entering same cycle
                self.trade_logger.log_trade(
                    instrument, signal, units, entry_price,
                    sl=order.get("sl", 0), tp=order.get("tp", 0),
                )
        except Exception as e:
            logger.error(f"Error scanning {instrument}: {e}")

    # -- main loop ---------------------------------------------------------
    def run(self):
        cycle = 0
        while self.running:
            cycle += 1
            if self.check_kill_switch():
                break

            self._rate_cache.clear()  # refresh conversion rates each cycle
            open_instruments = self.client.get_open_instruments()

            logger.info(f"\n[Cycle {cycle}] Scanning {len(Config.INSTRUMENTS)} pairs...")
            for instrument in Config.INSTRUMENTS:
                if self.check_kill_switch():
                    break
                self.scan_pair(instrument, open_instruments)

            account = self.client.get_account_details()
            if account:
                logger.info(f"Account balance: ${float(account.get('balance', 0)):.2f}")

            logger.info(f"Waiting {Config.POLL_INTERVAL}s until next scan...")
            for _ in range(Config.POLL_INTERVAL):
                if self.check_kill_switch():
                    break
                time.sleep(1)

        logger.info("🛑 Bot shutdown complete")
        logger.info(self.trade_logger.summary())


# ============================================================================
# ENTRY POINT
# ============================================================================


def _load_api_token():
    """Prefer oanda_config.API_TOKEN, fall back to the OANDA_API_TOKEN env var."""
    try:
        import oanda_config as config  # user-provided, git-ignored

        token = getattr(config, "API_TOKEN", None)
        if token:
            return token
    except ImportError:
        pass
    return os.getenv("OANDA_API_TOKEN")


def main():
    setup_logger()
    api_token = _load_api_token()

    problems = validate_config(api_token)
    if problems:
        logger.error("=" * 60)
        logger.error("CONFIG VALIDATION FAILED — bot will not start:")
        for p in problems:
            logger.error(f"  ✗ {p}")
        logger.error("=" * 60)
        raise SystemExit(1)

    bot = OandaBot(api_token)
    try:
        bot.run()
    except KeyboardInterrupt:
        logger.info("\n⚠️  Interrupted by user")
        bot.running = False
    except Exception as e:
        logger.critical(f"Fatal error: {e}", exc_info=True)


if __name__ == "__main__":
    main()
