#!/usr/bin/env python3
"""Why isn't the bot trading? — end-to-end live diagnostic.

    python3 diagnose.py

Runs the bot's OWN code paths against the live account and reports, in order,
every condition that can stop a trade from firing:

  1. config actually loaded      4. strategy signal right now (+ how close)
  2. account reachable           5. position sizing (catches 0-unit orders)
  3. candles fetchable           6. gates/filters, open + closed trades

Ends with a plain verdict. Read-only: it never places or closes anything.
"""
import sys
import oanda_trader as ot
from oanda_trader import Config, STRATEGIES

OK, BAD, WARN = "  [OK] ", "  [!!] ", "  [??] "
problems, notes = [], []

print("=" * 66)
print("BOT DIAGNOSTIC —", ", ".join(Config.INSTRUMENTS), "|", Config.STRATEGY,
      "|", Config.TIMEFRAME)
print("=" * 66)

# --- 1. config ------------------------------------------------------------
print("\n1) CONFIG")
print(f"     strategy={Config.STRATEGY}  timeframe={Config.TIMEFRAME}  "
      f"candles={Config.CANDLE_COUNT}")
print(f"     risk/trade=${Config.RISK_PER_TRADE}  min_open={Config.MIN_OPEN_TRADES}"
      f"  max_open={Config.MAX_OPEN_TRADES}")
print(f"     trend_filter={Config.TREND_FILTER}  htf_filter={Config.HTF_FILTER}  "
      f"analyzer={Config.ANALYZER}  news_veto={Config.NEWS_VETO}")
print(f"     atr_exits={Config.USE_ATR_EXITS}  dry_run={Config.DRY_RUN}")
if Config.DRY_RUN:
    problems.append("DRY_RUN is ON — the bot will never place a real order.")
    print(BAD + "DRY_RUN=true -> signals are logged but NO orders are sent")
if Config.STRATEGY == "breakout" and Config.CANDLE_COUNT <= Config.BREAKOUT_LOOKBACK:
    problems.append("CANDLE_COUNT <= BREAKOUT_LOOKBACK — never enough history.")

# --- 2. account -----------------------------------------------------------
print("\n2) ACCOUNT")
token = ot._load_api_token()
if not token:
    print(BAD + "No API token found (.env OANDA_API_TOKEN).")
    sys.exit(1)
client = ot.OandaClient(token)
acct = client.get_account_details()
if not acct:
    problems.append("Cannot reach the OANDA account (bad token or endpoint).")
    print(BAD + "account fetch FAILED")
else:
    print(OK + f"balance=${float(acct.get('balance',0)):,.2f}  "
               f"NAV=${float(acct.get('NAV',0)):,.2f}  "
               f"currency={acct.get('currency')}")

open_trades = client.get_open_trades()
print(f"     open trades: {len(open_trades)}")
try:
    led = ot.TradeLedger(Config.LOG_DIR)
    print(f"     closed-trade ledger: {len(led.rows)} recorded")
except Exception as e:
    print(WARN + f"ledger unavailable: {e}")

# --- 3-5. per instrument --------------------------------------------------
for inst in Config.INSTRUMENTS:
    print(f"\n3) MARKET DATA — {inst}")
    raw = client.get_candles(inst, granularity=Config.TIMEFRAME,
                             count=Config.CANDLE_COUNT)
    if not raw:
        problems.append(f"{inst}: candle fetch FAILED — instrument likely not "
                        f"available/tradeable on this account.")
        print(BAD + "candle fetch FAILED -> instrument unavailable on this account?")
        continue
    candles = ot.completed_candles(raw)
    print(OK + f"{len(candles)} completed candles  "
               f"last close={float(candles[-1]['mid']['c'])}")

    need = Config.BREAKOUT_LOOKBACK + 1 if Config.STRATEGY == "breakout" else 30
    if len(candles) < need:
        problems.append(f"{inst}: only {len(candles)} candles, need >= {need}.")
        print(BAD + f"not enough history (need >= {need})")
        continue

    print(f"\n4) SIGNAL — {inst}")
    det = STRATEGIES.get(Config.STRATEGY)
    raw_sig = det.get_signal(candles, inst) if det else None
    gated = ot.signal_for(candles, inst)
    print(f"     raw strategy signal : {raw_sig or 'none'}")
    print(f"     after filters/gates : {gated or 'none'}")
    if raw_sig and not gated:
        notes.append(f"{inst}: signal '{raw_sig}' was BLOCKED by a filter "
                     f"(trend_filter/news/analyzer).")
        print(WARN + "a signal fired but a FILTER blocked it")

    # how close to triggering? (breakout only)
    if Config.STRATEGY == "breakout":
        n = Config.BREAKOUT_LOOKBACK
        closes = [float(c["mid"]["c"]) for c in candles]
        prior, curr = closes[-(n + 1):-1], closes[-1]
        hi, lo = max(prior), min(prior)
        ps = ot.pip_size(inst)
        print(f"     {n}-bar high={hi:.2f}  low={lo:.2f}  current={curr:.2f}")
        print(f"     needs +{(hi-curr)/ps:,.0f} pts to BUY  |  "
              f"-{(curr-lo)/ps:,.0f} pts to SELL")
        if curr <= hi and curr >= lo:
            notes.append(f"{inst}: price is INSIDE the {n}-bar range — no breakout "
                         f"yet. This is normal waiting, not a fault.")

    print(f"\n5) SIZING — {inst}")
    q = inst.split("_")[-1]
    q2usd = 1.0 if q == "USD" else None
    if q2usd is None:
        px = client.get_price(f"{q}_USD", quiet=True)
        q2usd = px if px else (1.0 / client.get_price(f"USD_{q}", quiet=True)
                               if client.get_price(f"USD_{q}", quiet=True) else None)
    if not q2usd:
        problems.append(f"{inst}: cannot resolve quote->USD rate; sizing returns 0.")
        print(BAD + "no quote->USD conversion -> 0 units")
        continue
    stop_pips = Config.STOP_LOSS_PIPS
    if Config.USE_ATR_EXITS:
        a = ot.atr(candles, Config.ATR_EXIT_PERIOD)
        if a:
            stop_pips = max(1, round(Config.ATR_STOP_MULT * a / ot.pip_size(inst)))
    units = ot.PositionManager.calculate_units(inst, stop_pips, q2usd,
                                               risk_usd=Config.RISK_PER_TRADE)
    loss = units * stop_pips * ot.pip_size(inst) * q2usd
    print(f"     stop={stop_pips} pts -> units={units}  (loss at stop ~${loss:,.2f})")
    if units <= 0:
        problems.append(f"{inst}: position size computes to 0 units — NO trade can "
                        f"ever be placed. Raise OANDA_RISK_PER_TRADE.")
        print(BAD + "0 UNITS -> the bot physically cannot open a trade")

# --- verdict --------------------------------------------------------------
print("\n" + "=" * 66)
print("VERDICT")
print("=" * 66)
if problems:
    print("  BLOCKING PROBLEMS FOUND:")
    for p in problems:
        print(f"   - {p}")
else:
    print("  No blocking faults. The bot is configured correctly and CAN trade.")
    for n_ in notes:
        print(f"   - {n_}")
    if not notes:
        print("   - Waiting for a valid setup. This is normal.")
print()
