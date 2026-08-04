#!/usr/bin/env python3
"""
OANDA Multi-Pair 5-Minute Momentum Scalper  (Project Titan — Forex Division)

Momentum-following strategy across many pairs on 5-minute candles, built to run
safely against an OANDA v20 *practice* account.

Design notes / why the code looks the way it does:

  * Signals fire on **completed** candles only. OANDA streams the in-progress
    bar as the last element of the candle list; acting on it would evaluate a
    flickering, unfinished candle. We drop incomplete bars everywhere.
  * Position sizing converts each pair's pip value into the account currency
    (USD) so `$RISK_PER_TRADE` is honoured. (The account currency is verified at
    startup — non-USD accounts are refused rather than silently mis-sized.)
  * The stop-loss is sent as a fill-relative **distance**, so OANDA anchors it to
    the real fill price instead of an estimate. The take-profit uses an absolute
    price from the last closed candle (OANDA's TP-on-fill takes a price, not a
    distance).
  * API GETs retry on transient network errors; order POSTs never retry, so a
    dropped response can't cause a double fill.
  * Importing the module has no side effects (logging is configured in main()),
    which keeps the pure logic unit-testable.

Mode: DEMO practice endpoint by default. The live (fxtrade) endpoint is refused
unless OANDA_ALLOW_LIVE is set explicitly.
"""

import os
import json
import time
import logging
from datetime import datetime, timezone
from collections import defaultdict
from pathlib import Path

import requests

# ============================================================================
# CONFIGURATION
# ============================================================================


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return int(raw) if raw not in (None, "") else default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    return float(raw) if raw not in (None, "") else default


class Config:
    # OANDA Setup ------------------------------------------------------------
    ACCOUNT_ID = os.getenv("OANDA_ACCOUNT_ID", "101-001-39975042-001")
    # Practice (demo) by default; the live endpoint is api-fxtrade.oanda.com.
    API_URL = os.getenv("OANDA_API_URL", "https://api-fxpractice.oanda.com")
    ACCOUNT_CURRENCY = "USD"  # sizing math assumes USD; verified at startup

    INSTRUMENTS = [
        "EUR_USD", "GBP_USD", "USD_JPY", "USD_CHF", "AUD_USD",
        "NZD_USD", "EUR_GBP", "EUR_JPY", "GBP_JPY", "USD_CAD",
        "USD_SEK", "USD_NOK", "USD_CNH",
    ]

    # Trading Parameters -----------------------------------------------------
    # Candle granularity: S5/S10/S30, M1/M5/M15, H1... (OANDA v20 codes).
    TIMEFRAME = os.getenv("OANDA_TIMEFRAME", "M5")
    CANDLE_COUNT = _env_int("OANDA_CANDLE_COUNT", 60)
    RISK_PER_TRADE = _env_float("OANDA_RISK_PER_TRADE", 10.0)  # in ACCOUNT_CURRENCY

    # Strategy selection -----------------------------------------------------
    STRATEGY = os.getenv("OANDA_STRATEGY", "rsi")  # "rsi" or "ema_pullback"

    # Momentum (RSI) thresholds (env-tunable) --------------------------------
    RSI_PERIOD = _env_int("OANDA_RSI_PERIOD", 14)
    RSI_OVERSOLD = _env_float("OANDA_RSI_OVERSOLD", 30)     # dip within uptrend -> buy
    RSI_OVERBOUGHT = _env_float("OANDA_RSI_OVERBOUGHT", 70)  # rally within downtrend -> sell
    TREND_PERIOD = _env_int("OANDA_TREND_PERIOD", 3)

    # EMA pullback strategy (env-tunable) ------------------------------------
    EMA_FAST = _env_int("OANDA_EMA_FAST", 9)
    EMA_SLOW = _env_int("OANDA_EMA_SLOW", 21)

    # Breakout strategy ------------------------------------------------------
    BREAKOUT_LOOKBACK = _env_int("OANDA_BREAKOUT_LOOKBACK", 20)

    # Bollinger mean-reversion strategy --------------------------------------
    BOLL_PERIOD = _env_int("OANDA_BOLL_PERIOD", 20)
    BOLL_K = _env_float("OANDA_BOLL_K", 2.0)

    # Risk Management --------------------------------------------------------
    STOP_LOSS_PIPS = _env_int("OANDA_STOP_LOSS_PIPS", 20)
    TAKE_PROFIT_PIPS = _env_int("OANDA_TAKE_PROFIT_PIPS", 40)
    MAX_OPEN_TRADES = _env_int("OANDA_MAX_OPEN_TRADES", 8)
    # Always keep at least this many trades open (fills with trend-following
    # fallback entries when strategy signals aren't enough).
    MIN_OPEN_TRADES = _env_int("OANDA_MIN_OPEN_TRADES", 5)
    ONE_POSITION_PER_INSTRUMENT = True   # no stacking on every candle

    # Profit-take rule: close a trade once its unrealized profit reaches this
    # percent of the margin committed to that trade ("10% back -> sell").
    PROFIT_TAKE_PCT = _env_float("OANDA_PROFIT_TAKE_PCT", 10.0)

    # Safety -----------------------------------------------------------------
    # DRY_RUN: log intended orders, send nothing. Default False so the demo
    # endpoint can actually place practice orders (its whole purpose).
    DRY_RUN = _env_bool("OANDA_DRY_RUN", False)
    # The live endpoint is refused unless this is explicitly turned on.
    ALLOW_LIVE = _env_bool("OANDA_ALLOW_LIVE", False)

    # Operational ------------------------------------------------------------
    POLL_INTERVAL = _env_int("OANDA_POLL_INTERVAL", 30)
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
    if Config.STOP_LOSS_PIPS <= 0:
        problems.append("STOP_LOSS_PIPS must be positive")
    if Config.STRATEGY not in STRATEGIES:
        problems.append(
            f"OANDA_STRATEGY={Config.STRATEGY!r} is unknown; "
            f"choose one of {sorted(STRATEGIES)}"
        )
    if Config.EMA_FAST >= Config.EMA_SLOW:
        problems.append("OANDA_EMA_FAST must be < OANDA_EMA_SLOW")
    valid_granularities = {
        "S5", "S10", "S15", "S30", "M1", "M2", "M4", "M5", "M10", "M15",
        "M30", "H1", "H2", "H3", "H4", "H6", "H8", "H12", "D", "W", "M",
    }
    if Config.TIMEFRAME not in valid_granularities:
        problems.append(f"OANDA_TIMEFRAME={Config.TIMEFRAME!r} is not a valid OANDA granularity")
    if Config.MIN_OPEN_TRADES > Config.MAX_OPEN_TRADES:
        problems.append(
            f"OANDA_MIN_OPEN_TRADES ({Config.MIN_OPEN_TRADES}) must be <= "
            f"OANDA_MAX_OPEN_TRADES ({Config.MAX_OPEN_TRADES})"
        )
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


def completed_candles(candles):
    """Drop OANDA's in-progress (incomplete) trailing candle."""
    return [c for c in candles if c.get("complete")]


def candle_epoch(time_str):
    """Parse an OANDA candle 'time' to an int epoch, accepting UNIX or RFC3339.

    OANDA returns UNIX ('1785865500.000000000') when the Accept-Datetime-Format
    header is honoured, and RFC3339 ('2026-08-04T17:40:00.000000000Z') otherwise.
    We accept both so the loop can't break on a header/format change.
    """
    try:
        return int(float(time_str))  # UNIX seconds
    except (TypeError, ValueError):
        pass
    # RFC3339, e.g. 2026-08-04T17:40:00.000000000Z -> drop fractional secs & Z.
    base = time_str.rstrip("Z").split(".")[0]
    dt = datetime.strptime(base, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


# ============================================================================
# OANDA API CLIENT
# ============================================================================


class OandaClient:
    """Wrapper for OANDA v20 REST API."""

    def __init__(self, api_token):
        self.api_token = api_token
        self.headers = {
            "Authorization": f"Bearer {api_token}",
            "Accept-Datetime-Format": "UNIX",
            "Content-Type": "application/json",
        }

    def _request(self, method, path, *, params=None, body=None, retry=True):
        """Perform a request. Returns parsed JSON dict (or None on failure).

        GETs retry on transient network errors; POSTs never retry so a dropped
        response can't produce a duplicate order. HTTP error bodies are logged.
        """
        url = f"{Config.API_URL}{path}"
        attempts = 3 if retry else 1
        for attempt in range(attempts):
            try:
                resp = requests.request(
                    method, url, headers=self.headers,
                    params=params, json=body, timeout=10,
                )
                try:
                    data = resp.json() if resp.content else {}
                except ValueError:
                    data = {}
                if resp.status_code >= 400:
                    logger.error(
                        f"{method} {path} -> {resp.status_code}: {resp.text[:400]}"
                    )
                return data
            except requests.exceptions.RequestException as e:
                if attempt < attempts - 1:
                    time.sleep(2 ** attempt)
                    continue
                logger.error(f"{method} {path} failed after {attempts} attempt(s): {e}")
                return None

    def get_candles(self, instrument, granularity="M5", count=100):
        """Fetch recent candles for an instrument (oldest -> newest)."""
        data = self._request(
            "GET",
            f"/v3/instruments/{instrument}/candles",
            params={"granularity": granularity, "count": count, "price": "M"},
        )
        return (data or {}).get("candles", [])

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
        """Fetch current account balance, currency and margin info."""
        data = self._request("GET", f"/v3/accounts/{Config.ACCOUNT_ID}")
        return (data or {}).get("account", {})

    def get_open_instruments(self):
        """Set of instruments with a currently open position."""
        data = self._request("GET", f"/v3/accounts/{Config.ACCOUNT_ID}/openPositions")
        if not data:
            return set()
        return {p["instrument"] for p in data.get("positions", [])}

    def get_open_trades(self):
        """List of open trades (each has id, instrument, unrealizedPL, marginUsed)."""
        data = self._request("GET", f"/v3/accounts/{Config.ACCOUNT_ID}/openTrades")
        return (data or {}).get("trades", [])

    def place_order(self, instrument, units, entry_price, stop_loss_pips, take_profit_pips):
        """Place a market order with a fill-relative SL distance and a TP price."""
        ps = pip_size(instrument)
        decimals = price_decimals(instrument)

        sl_distance = stop_loss_pips * ps
        if units > 0:   # BUY
            tp_price = entry_price + take_profit_pips * ps
        else:           # SELL
            tp_price = entry_price - take_profit_pips * ps

        order_body = {
            "order": {
                "instrument": instrument,
                "units": str(int(units)),
                "type": "MARKET",
                "timeInForce": "FOK",
                "positionFill": "DEFAULT",
                # SL as a distance -> anchored to the real fill price by OANDA.
                "stopLossOnFill": {"distance": f"{sl_distance:.{decimals}f}"},
                "takeProfitOnFill": {"price": f"{tp_price:.{decimals}f}"},
            }
        }

        if Config.DRY_RUN:
            logger.info(
                f"[DRY-RUN] would place {instrument} {int(units)} units @ "
                f"~{entry_price:.{decimals}f} | SL dist {sl_distance:.{decimals}f} | "
                f"TP {tp_price:.{decimals}f}"
            )
            return {"dryRun": True, "sl_distance": sl_distance, "tp": tp_price,
                    "fill_price": entry_price, "trade_id": None}

        data = self._request(
            "POST", f"/v3/accounts/{Config.ACCOUNT_ID}/orders",
            body=order_body, retry=False,
        )
        if data is None:
            return None

        fill = data.get("orderFillTransaction")
        if fill:
            trade_id = fill.get("tradeOpened", {}).get("tradeID")
            logger.info(
                f"✓ ORDER FILLED: {instrument} {int(units)} units @ {fill.get('price')} "
                f"| trade {trade_id} | SL dist {sl_distance:.{decimals}f} | "
                f"TP {tp_price:.{decimals}f}"
            )
            data["fill_price"] = float(fill.get("price", entry_price))
            data["tp"] = tp_price
            data["sl_distance"] = sl_distance
            data["trade_id"] = trade_id
            return data

        # Business reject (arrives as 201/400 with a reject/cancel transaction).
        reject = data.get("orderRejectTransaction") or data.get("orderCancelTransaction")
        reason = reject.get("reason") if reject else data.get("errorMessage", "unknown")
        logger.warning(f"Order NOT filled for {instrument}: {reason}")
        return None

    def close_trade(self, trade_id):
        """Close a single trade by its id (never touches other positions).

        Preferred over closing 'ALL' units of an instrument, which would also
        close any pre-existing position the bot did not open.
        """
        data = self._request(
            "PUT", f"/v3/accounts/{Config.ACCOUNT_ID}/trades/{trade_id}/close",
            body={"units": "ALL"}, retry=False,
        )
        if data is None:
            return None
        fill = data.get("orderFillTransaction")
        if fill:
            logger.info(f"✓ CLOSED trade {trade_id} @ {fill.get('price')} | pl {fill.get('pl')}")
        return data


# ============================================================================
# MOMENTUM DETECTOR   (strategy logic preserved)
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
        """Combined momentum signal: RSI + trend confirmation -> 'BUY'/'SELL'/None.

        `candles` are expected to be completed candles.
        """
        needed = max(20, Config.RSI_PERIOD + 1, Config.TREND_PERIOD)
        if len(candles) < needed:
            return None

        closes = [float(c["mid"]["c"]) for c in candles]
        rsi = MomentumDetector.calculate_rsi(closes, Config.RSI_PERIOD)
        trend = MomentumDetector.detect_trend(candles, Config.TREND_PERIOD)
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
# EMA PULLBACK DETECTOR
# ============================================================================


def ema_series(values, period):
    """Exponential moving average series (same length as `values`)."""
    if not values:
        return []
    k = 2.0 / (period + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


class EmaPullbackDetector:
    """Trend-pullback entries using a fast/slow EMA.

    Trend is set by the fast EMA vs the slow EMA. We then wait for price to pull
    back to (through) the fast EMA and enter only when the trend *resumes*:

      * BUY  — fast EMA > slow EMA (uptrend), the previous close was below the
               fast EMA (the pullback), and the current close closed back above it.
      * SELL — fast EMA < slow EMA (downtrend), the previous close was above the
               fast EMA, and the current close closed back below it.

    This fires far less often than chasing breakouts, but only on trend
    continuation after a dip/rally into the moving average.
    """

    name = "ema_pullback"

    @staticmethod
    def get_signal(candles, instrument):
        needed = Config.EMA_SLOW + 2
        if len(candles) < needed:
            return None

        closes = [float(c["mid"]["c"]) for c in candles]
        fast = ema_series(closes, Config.EMA_FAST)
        slow = ema_series(closes, Config.EMA_SLOW)

        fast_now, slow_now = fast[-1], slow[-1]
        prev_close, curr_close = closes[-2], closes[-1]
        prev_fast = fast[-2]

        if fast_now > slow_now and prev_close < prev_fast and curr_close > fast_now:
            logger.debug(
                f"  {instrument}: uptrend (EMA{Config.EMA_FAST}>{Config.EMA_SLOW}), "
                f"pullback resumed above EMA -> BUY"
            )
            return "BUY"
        if fast_now < slow_now and prev_close > prev_fast and curr_close < fast_now:
            logger.debug(
                f"  {instrument}: downtrend (EMA{Config.EMA_FAST}<{Config.EMA_SLOW}), "
                f"pullback resumed below EMA -> SELL"
            )
            return "SELL"
        return None


# ============================================================================
# BREAKOUT DETECTOR  (Donchian-style, trend following)
# ============================================================================


class BreakoutDetector:
    """Enter on a close breaking the recent range — momentum/trend continuation.

    * BUY  — current close is the highest close of the last ``BREAKOUT_LOOKBACK``
             bars (an upside breakout).
    * SELL — current close is the lowest close of that window.
    """

    name = "breakout"

    @staticmethod
    def get_signal(candles, instrument):
        n = Config.BREAKOUT_LOOKBACK
        if len(candles) < n + 1:
            return None
        closes = [float(c["mid"]["c"]) for c in candles]
        prior = closes[-(n + 1):-1]   # the N closes before the current one
        curr = closes[-1]
        if curr > max(prior):
            logger.debug(f"  {instrument}: close {curr} broke {n}-bar high -> BUY")
            return "BUY"
        if curr < min(prior):
            logger.debug(f"  {instrument}: close {curr} broke {n}-bar low -> SELL")
            return "SELL"
        return None


# ============================================================================
# BOLLINGER MEAN-REVERSION DETECTOR
# ============================================================================


class BollingerReversionDetector:
    """Fade stretches away from the mean (counter-trend).

    Computes a moving average and standard deviation over ``BOLL_PERIOD`` closes.
    * BUY  — close is below the lower band (mean - K*std): oversold, expect a bounce.
    * SELL — close is above the upper band (mean + K*std): overbought, expect a fade.
    """

    name = "bollinger"

    @staticmethod
    def get_signal(candles, instrument):
        n = Config.BOLL_PERIOD
        if len(candles) < n:
            return None
        closes = [float(c["mid"]["c"]) for c in candles]
        window = closes[-n:]
        mean = sum(window) / n
        var = sum((x - mean) ** 2 for x in window) / n
        std = var ** 0.5
        if std == 0:
            return None
        curr = closes[-1]
        if curr < mean - Config.BOLL_K * std:
            logger.debug(f"  {instrument}: below lower Bollinger band -> BUY")
            return "BUY"
        if curr > mean + Config.BOLL_K * std:
            logger.debug(f"  {instrument}: above upper Bollinger band -> SELL")
            return "SELL"
        return None


# Strategy dispatch -----------------------------------------------------------
STRATEGIES = {
    "rsi": MomentumDetector,
    "ema_pullback": EmaPullbackDetector,
    "breakout": BreakoutDetector,
    "bollinger": BollingerReversionDetector,
}


def signal_for(candles, instrument):
    """Return the entry signal from the currently-selected strategy."""
    detector = STRATEGIES.get(Config.STRATEGY, MomentumDetector)
    return detector.get_signal(candles, instrument)


def should_take_profit(unrealized_pl, margin_used, pct):
    """True when a trade's unrealized return on its margin reaches ``pct`` percent."""
    if margin_used <= 0:
        return False
    return (unrealized_pl / margin_used) * 100.0 >= pct


def fallback_direction(candles):
    """Trend-following direction (BUY/SELL) used to top up to the minimum trade
    count when strategy signals are scarce: long if the fast EMA is at/above the
    slow EMA, short otherwise."""
    closes = [float(c["mid"]["c"]) for c in candles]
    fast = ema_series(closes, Config.EMA_FAST)[-1]
    slow = ema_series(closes, Config.EMA_SLOW)[-1]
    return "BUY" if fast >= slow else "SELL"


# ============================================================================
# POSITION MANAGER   (correct sizing)
# ============================================================================


class PositionManager:
    """Size positions so each trade risks exactly RISK_PER_TRADE (USD)."""

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
        self._rate_cache = {}  # quote currency -> USD rate, refreshed each cycle

        mode = "DRY-RUN" if Config.DRY_RUN else ("LIVE" if Config.is_live_endpoint() else "DEMO")
        logger.info("=" * 60)
        logger.info("🤖 OANDA MULTI-PAIR 5-MIN MOMENTUM BOT")
        logger.info("=" * 60)
        logger.info(f"Account: {Config.ACCOUNT_ID}")
        logger.info(f"Mode: {mode}")
        logger.info(f"Strategy: {Config.STRATEGY}")
        logger.info(f"Risk per trade: ${Config.RISK_PER_TRADE}")
        logger.info(f"Stop Loss: {Config.STOP_LOSS_PIPS} pips | Take Profit: {Config.TAKE_PROFIT_PIPS} pips")
        logger.info(f"Profit-take: +{Config.PROFIT_TAKE_PCT}% of margin | "
                    f"Open trades: min {Config.MIN_OPEN_TRADES}, max {Config.MAX_OPEN_TRADES}")
        logger.info(f"Monitoring {len(Config.INSTRUMENTS)} pairs")
        logger.info(f"Kill switch: create '{Config.KILL_SWITCH_FILE}' to stop")
        logger.info("=" * 60)

    # -- startup checks ----------------------------------------------------
    def preflight(self):
        """Verify the account is reachable and its currency matches our sizing."""
        acct = self.client.get_account_details()
        if not acct:
            logger.error("Preflight failed: could not fetch account details "
                         "(check the API token and OANDA_ACCOUNT_ID).")
            return False
        currency = acct.get("currency")
        if currency != Config.ACCOUNT_CURRENCY:
            logger.error(
                f"Account currency is {currency!r}, but sizing assumes "
                f"{Config.ACCOUNT_CURRENCY}. Aborting to avoid mis-sizing — "
                f"use a {Config.ACCOUNT_CURRENCY} practice account."
            )
            return False
        logger.info(
            f"Preflight OK — account {Config.ACCOUNT_ID} currency={currency} "
            f"balance=${float(acct.get('balance', 0)):.2f}"
        )
        # Surface positions that already exist so the operator isn't surprised;
        # the bot leaves these alone (it only manages trades it opens).
        preexisting = self.client.get_open_instruments()
        if preexisting:
            logger.info(f"Pre-existing open positions (left untouched): {sorted(preexisting)}")
        return True

    # -- helpers -----------------------------------------------------------
    def check_kill_switch(self):
        if os.path.exists(Config.KILL_SWITCH_FILE):
            logger.warning("⚠️  KILL SWITCH ACTIVATED - shutting down bot")
            self.running = False
            return True
        return False

    def quote_to_usd(self, instrument):
        """Rate to convert the pair's quote currency into USD (cached per cycle)."""
        quote = instrument.split("_")[1]
        if quote == "USD":
            return 1.0
        if quote in self._rate_cache:
            return self._rate_cache[quote]

        rate = None
        direct = self.client.get_price(f"{quote}_USD")   # e.g. GBP_USD
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

    # -- order placement (shared by signals and minimum-fill) --------------
    def _open_trade(self, instrument, direction, candles, open_instruments, tag=""):
        """Size and submit one trade in `direction` ('BUY'/'SELL'). Returns bool."""
        q2usd = self.quote_to_usd(instrument)
        units = PositionManager.calculate_units(instrument, Config.STOP_LOSS_PIPS, q2usd)
        if units <= 0:
            logger.warning(f"Skip {instrument}: computed 0 units (sizing unavailable)")
            return False
        if direction == "SELL":
            units = -units

        entry_price = float(candles[-1]["mid"]["c"])
        label = f"{direction}{(' ' + tag) if tag else ''}"
        logger.info(f"\n📊 {label}: {instrument} ({units} units)")
        order = self.client.place_order(
            instrument, units, entry_price, Config.STOP_LOSS_PIPS, Config.TAKE_PROFIT_PIPS,
        )
        if order:
            open_instruments.add(instrument)
            self.trade_logger.log_trade(
                instrument, label, units, order.get("fill_price", entry_price),
                sl=order.get("sl_distance", 0), tp=order.get("tp", 0),
            )
            return True
        return False

    # -- profit-take rule: close a trade at +PROFIT_TAKE_PCT% of its margin -
    def manage_open_trades(self):
        for t in self.client.get_open_trades():
            upl = float(t.get("unrealizedPL", 0) or 0)
            margin = float(t.get("marginUsed", 0) or 0)
            if should_take_profit(upl, margin, Config.PROFIT_TAKE_PCT):
                pct = (upl / margin * 100) if margin else 0
                logger.info(f"💰 PROFIT-TAKE {t.get('instrument')} #{t.get('id')}: "
                            f"+{pct:.1f}% of margin (>= {Config.PROFIT_TAKE_PCT}%), closing")
                self.client.close_trade(t.get("id"))

    # -- keep at least MIN_OPEN_TRADES open (trend-following fallback) ------
    def ensure_minimum_trades(self, open_instruments):
        for instrument in Config.INSTRUMENTS:
            if len(open_instruments) >= Config.MIN_OPEN_TRADES:
                break
            if instrument in open_instruments:
                continue
            raw = self.client.get_candles(instrument, granularity=Config.TIMEFRAME,
                                          count=Config.CANDLE_COUNT)
            candles = completed_candles(raw)
            if len(candles) < Config.EMA_SLOW + 2:
                continue
            self._open_trade(instrument, fallback_direction(candles),
                             candles, open_instruments, tag="(min-fill)")

    # -- per-pair scan -----------------------------------------------------
    def scan_pair(self, instrument, open_instruments):
        try:
            raw = self.client.get_candles(instrument, granularity=Config.TIMEFRAME,
                                          count=Config.CANDLE_COUNT)
            candles = completed_candles(raw)
            if len(candles) < 20:
                return

            # De-dup on the latest *completed* candle: act once per closed bar.
            latest_time = candle_epoch(candles[-1]["time"])
            if latest_time <= self.last_candle_time[instrument]:
                return
            self.last_candle_time[instrument] = latest_time

            signal = signal_for(candles, instrument)
            if not signal:
                return

            if Config.ONE_POSITION_PER_INSTRUMENT and instrument in open_instruments:
                logger.info(f"Skip {instrument}: position already open")
                return
            if len(open_instruments) >= Config.MAX_OPEN_TRADES:
                logger.info(f"Skip {instrument}: max open trades ({Config.MAX_OPEN_TRADES}) reached")
                return

            self._open_trade(instrument, signal, candles, open_instruments)
        except Exception as e:
            logger.error(f"Error scanning {instrument}: {e}")

    # -- main loop ---------------------------------------------------------
    def run(self):
        if not self.preflight():
            logger.error("Aborting: preflight checks failed.")
            return

        cycle = 0
        while self.running:
            cycle += 1
            if self.check_kill_switch():
                break

            self._rate_cache.clear()  # refresh conversion rates each cycle

            self.manage_open_trades()  # 1) take profits at +PROFIT_TAKE_PCT% of margin
            open_instruments = self.client.get_open_instruments()

            logger.info(f"\n[Cycle {cycle}] Scanning {len(Config.INSTRUMENTS)} pairs "
                        f"({len(open_instruments)} open)...")
            for instrument in Config.INSTRUMENTS:  # 2) strategy entries
                if self.check_kill_switch():
                    break
                self.scan_pair(instrument, open_instruments)

            if not self.check_kill_switch():       # 3) top up to the minimum
                self.ensure_minimum_trades(open_instruments)

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
