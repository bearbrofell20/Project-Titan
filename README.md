# Project Titan — Auto Trader

A small, safety-first automated trading toolkit, written in Python. It currently
covers two venues:

| Venue  | Market            | Module            | Command                     |
|--------|-------------------|-------------------|-----------------------------|
| Kalshi | event contracts   | `kalshi_trader/`  | `python -m kalshi_trader …` |
| OANDA  | forex (spot FX)   | `oanda_trader.py` | `python oanda_trader.py`    |

Both fetch live market data, run a strategy, gate every proposed trade through
hard risk limits, and then either **log** the trade or submit it. The pure logic
— strategies, risk, sizing, indicators — is unit-tested and needs no network or
credentials to run. See the **Forex (OANDA)** section below for that bot.

---

## Kalshi — event-contracts trader

A safety-first bot for the [Kalshi](https://kalshi.com) event-contracts exchange.

It fetches live markets, runs a pluggable strategy over them, gates every
proposed trade through hard risk limits, and then either **logs** the trade
(dry-run, the default) or submits it to Kalshi (live).

> ⚠️ **Trading involves real money and real risk.** Prediction-market contracts
> can expire worthless. This project defaults to dry-run and ships conservative
> risk limits, but it is a starting framework, not financial advice. Understand
> the code and start on the `demo` environment before ever going live.

## Layout

```
kalshi_trader/
  config.py        # env / credential loading, endpoints, risk defaults
  models.py        # Market, Position, OrderIntent (money kept in integer cents)
  client.py        # authenticated REST client (RSA-PSS request signing)
  risk.py          # RiskManager — order-size, position, exposure, daily-loss caps
  strategies/
    base.py        # Strategy interface (pure: state in, order intents out)
    threshold.py   # buy under-priced Yes / No vs. a fair-value estimate
    momentum.py    # moving-average crossover on last traded price
  engine.py        # the loop: data -> strategy -> risk -> log or submit
  cli.py           # `python -m kalshi_trader ...`
tests/             # unit tests for models, risk, strategies, and the engine
```

## Install

```bash
pip install -r requirements.txt
```

The strategy/risk/model layer and its tests only need the standard library;
`requests` and `cryptography` are required for live API calls.

## Configure

```bash
cp .env.example .env
# edit .env: set KALSHI_API_KEY_ID and KALSHI_PRIVATE_KEY_PATH
```

Create an API key in the Kalshi web app — you get a **key id** and a downloadable
**RSA private key** (`.pem`). Point `KALSHI_PRIVATE_KEY_PATH` at that file.
`.env` and `*.pem` keys are git-ignored.

Every request to the authenticated API is signed with RSA-PSS/SHA-256 over
`{timestamp_ms}{METHOD}{path}`, per Kalshi's API-key auth scheme.

## Use

```bash
# List open markets (public data, no credentials needed)
python -m kalshi_trader markets --limit 10

# Account balance / positions (needs credentials)
python -m kalshi_trader balance
python -m kalshi_trader positions

# Dry-run a strategy — logs intended trades, submits nothing
python -m kalshi_trader run --strategy momentum --max-ticks 5

# Threshold strategy with your fair-value estimates
python -m kalshi_trader run --strategy threshold \
    --fair-values examples/fair_values.example.json --max-ticks 5

# Live trading: requires --live AND a typed "TRADE" confirmation
python -m kalshi_trader --env demo run --strategy threshold --live
```

## Safety model

Trades only reach the exchange when **all** of these are true:

1. `KALSHI_DRY_RUN=false` (or `--live` on the CLI), and
2. you type `TRADE` at the live-run confirmation prompt, and
3. the order passes every `RiskManager` limit:
   - `max_contracts_per_order` — cap on a single order's size
   - `max_position_per_market` — cap on net contracts held in one market
   - `max_open_exposure_cents` — cap on total capital at risk across markets
   - `max_daily_loss_cents` — circuit breaker that halts new orders for the day

All limits live in `.env` / `Config` so you can tune them without touching code.

## Writing a strategy

Subclass `Strategy` and return `OrderIntent`s from `generate`. Strategies never
touch the network — the engine handles data, risk, and execution — so they stay
easy to reason about and test.

```python
from kalshi_trader.models import Action, OrderIntent, OrderType, Side
from kalshi_trader.strategies.base import Strategy

class BuyEverythingCheap(Strategy):
    name = "cheap"
    def generate(self, markets, positions):
        out = []
        for m in markets:
            if m.is_tradable and m.yes_ask is not None and m.yes_ask < 20:
                out.append(OrderIntent(
                    ticker=m.ticker, action=Action.BUY, side=Side.YES,
                    quantity=1, order_type=OrderType.LIMIT,
                    limit_price_cents=m.yes_ask, reason="yes under 20c",
                ))
        return out
```

Register it in `kalshi_trader/strategies/__init__.py`'s `REGISTRY` to expose it
to the CLI.

---

## Forex (OANDA) — multi-pair momentum scalper

`oanda_trader.py` scans 13 currency pairs on 5-minute candles and trades a
momentum signal (RSI dip/rally confirmed by a short-term trend), sizing every
order to risk a fixed dollar amount and attaching a stop-loss and take-profit.

### Configure

Use a **practice** account and token to start.

```bash
export OANDA_API_TOKEN='your-practice-token'
export OANDA_ACCOUNT_ID='101-001-XXXXXXX-001'
# or: cp oanda_config.example.py oanda_config.py  and fill in API_TOKEN
```

`oanda_config.py`, `trade_logs/` and `KILL_SWITCH.txt` are git-ignored.

### Run

```bash
python oanda_trader.py            # demo endpoint, places practice orders
OANDA_DRY_RUN=true python oanda_trader.py   # log intended orders, send nothing
```

Stop it any time by creating the kill-switch file: `touch KILL_SWITCH.txt`.

### Key settings (env vars)

| Variable                 | Default                          | Meaning                                   |
|--------------------------|----------------------------------|-------------------------------------------|
| `OANDA_API_TOKEN`        | —                                | v20 API token (required)                  |
| `OANDA_ACCOUNT_ID`       | `101-001-39975042-001`           | account to trade                          |
| `OANDA_API_URL`          | `https://api-fxpractice.oanda.com` | demo endpoint; live is `api-fxtrade`    |
| `OANDA_STRATEGY`         | `rsi`                            | `rsi` or `ema_pullback` (see below)       |
| `OANDA_RISK_PER_TRADE`   | `10.0`                           | USD risked per trade                      |
| `OANDA_DRY_RUN`          | `false`                          | `true` = log only, submit nothing         |
| `OANDA_ALLOW_LIVE`       | `false`                          | must be `yes` to use the real-money endpoint |
| `OANDA_MAX_OPEN_TRADES`  | `8`                              | cap on concurrent open positions          |
| `OANDA_MIN_OPEN_TRADES`  | `5`                              | always keep at least this many open (trend-fallback fills the gap) |
| `OANDA_PROFIT_TAKE_PCT`  | `10`                             | close a trade at +this% of its margin     |

### Strategies

Pick one with `OANDA_STRATEGY`:

* **`rsi`** (default) — buys an RSI dip inside a short uptrend, sells an RSI
  rally inside a downtrend. Tunable: `OANDA_RSI_PERIOD`, `OANDA_RSI_OVERSOLD`,
  `OANDA_RSI_OVERBOUGHT`, `OANDA_TREND_PERIOD`.
* **`ema_pullback`** — identifies the trend with a fast/slow EMA (fast above slow
  = uptrend), waits for price to pull back through the fast EMA, and enters only
  when the trend **resumes** (close back across the fast EMA). Fewer but
  higher-quality entries than chasing breakouts. Tunable: `OANDA_EMA_FAST`
  (default 9), `OANDA_EMA_SLOW` (default 21).
* **`breakout`** — Donchian-style trend following: buys a close that makes a new
  `OANDA_BREAKOUT_LOOKBACK`-bar high (default 20), sells a new low.
* **`bollinger`** — mean reversion: buys below the lower Bollinger band and sells
  above the upper band. Tunable: `OANDA_BOLL_PERIOD` (20), `OANDA_BOLL_K` (2.0).
* **`stochastic`** — mean reversion on the Stochastic oscillator: buys when %D is
  oversold and %K turns back up through it, sells the overbought mirror. Waits
  for the turn, not just the extreme. Tunable: `OANDA_STOCH_PERIOD` (14),
  `OANDA_STOCH_SMOOTH` (3), `OANDA_STOCH_OVERSOLD` (20), `OANDA_STOCH_OVERBOUGHT` (80).

```bash
OANDA_STRATEGY=ema_pullback python oanda_trader.py
```

### Backtest — test every strategy fast

Compare all strategies over historical candles instead of waiting a week each:

```bash
python backtest.py             # compare ALL strategies (1000 M5 bars)
python backtest.py all 2000    # ~7 days of history
python backtest.py bollinger   # one strategy
```

It replays each strategy bar by bar, simulating the same SL/TP exits with each
later bar's high/low (stop assumed first if a bar spans both), and prints trades,
win rate, net pips, profit factor, max drawdown and a dollar estimate per
strategy. It ignores spread/slippage/financing, so treat it as a **relative
ranking**, not a profit promise — confirm the winner on the live demo.

### Unified dashboard (both bots)

One dashboard watches **both** trading bots at once:

```bash
python dashboard.py     # then open http://localhost:8080
```

* **OANDA · Forex** — balance / NAV / realized + unrealized P/L, open positions
  with live P/L, a per-pair signal table (reusing the bot's own logic), and
  recent trades.
* **Kalshi · Event Contracts** — balance and open positions.

Each venue is independent: if a venue's credentials aren't configured it shows
"not configured" instead of erroring, so you can watch OANDA-only, Kalshi-only,
or both. Auto-refreshes every few seconds; tokens stay server-side (the browser
only talks to localhost). Knobs: `DASHBOARD_PORT` (default 8080),
`DASHBOARD_REFRESH` seconds (default 8).

### Running both bots together

`run_all.py` launches the OANDA bot + dashboard in one process. To also run the
Kalshi bot under the same dashboard, set `KALSHI_ENABLE=true` (with Kalshi
credentials configured — see the Kalshi section above):

```bash
KALSHI_ENABLE=true python run_all.py     # both bots + dashboard
```

The Kalshi bot defaults to dry-run (`KALSHI_DRY_RUN=true`) until you opt in.

### Did it pass? — performance report

At the end of a demo run, grade it:

```bash
python report.py        # all closed trades on the account
python report.py 7      # just the last 7 days
```

Pulls closed trades from OANDA (realised P/L, the source of truth) and prints
win rate, net P/L, profit factor, best/worst, and a per-instrument breakdown.
This is your go/no-go before ever risking real money.

### Running 24/7

The bot and dashboard are long-running processes. Run them together with:

```bash
python run_all.py     # bot trades; dashboard on http://localhost:8080
```

For always-on operation you want a host that stays up. Options, easiest first:

**Docker (recommended — any always-on machine or cloud VM):**

```bash
# put OANDA_API_TOKEN, OANDA_ACCOUNT_ID, OANDA_STRATEGY in a local .env
docker compose up -d --build     # runs detached, restarts on crash/reboot
docker compose logs -f           # watch it;  open http://localhost:8080
docker compose down              # stop
```

**systemd (Linux VPS / Raspberry Pi):** see `deploy/titan.service` — copy it to
`/etc/systemd/system/`, put your vars in `/etc/titan/titan.env`, then
`sudo systemctl enable --now titan`. It restarts on crash and on reboot.

**Quick and dirty (any Linux/Mac box you leave on):**

```bash
nohup python run_all.py > titan.out 2>&1 &   # keeps running after you log out
```

A tiny VPS (~$5/month) or a Raspberry Pi left on at home is the cheapest true
24/7 setup. The forex market runs ~24/5 (closed weekends), so the bot idles over
the weekend and resumes Monday automatically.

**What about Google Colab?** It works for a *short, supervised* run but **not for
real 24/7**: Colab disconnects after ~90 min idle, caps sessions around 12 h, and
its terms discourage unattended background compute — it will stop and the bot
stops with it. If you just want to try it from Colab, in a cell:

```python
!pip -q install requests
import os
os.environ["OANDA_API_TOKEN"]  = "your-practice-token"
os.environ["OANDA_ACCOUNT_ID"] = "101-001-39975042-001"
os.environ["OANDA_STRATEGY"]   = "ema_pullback"
!git clone https://github.com/bearbrofell20/project-titan.git
%cd project-titan
!python oanda_trader.py          # runs until the Colab session drops
```

(The dashboard needs a public tunnel to view from Colab, e.g. `pyngrok`, since
its server is inside the Colab VM — but given the disconnect limits, a real host
is the better answer.)

### Safety model

* Defaults to the **practice** endpoint. The live (`fxtrade`) endpoint is
  **refused at startup** unless `OANDA_ALLOW_LIVE=yes` is set explicitly.
* `OANDA_DRY_RUN=true` logs intended orders without sending any.
* One position per instrument and a `MAX_OPEN_TRADES` cap prevent the loop from
  stacking positions every candle.
* Each cycle the bot (1) closes any trade up **+`PROFIT_TAKE_PCT`% of its
  margin**, (2) takes strategy entries, then (3) tops up to
  **`MIN_OPEN_TRADES`** with trend-following fallback entries. Note: forcing a
  minimum means some entries are lower-conviction, and several forced longs at
  once are correlated risk — size and thresholds are yours to tune.

### Fixes applied to the original scalper

This integrated version corrects two bugs in the first draft:

1. **Position sizing was ~100× too large.** The old pip-cost constant sized
   EUR/USD at 500,000 units (~$1,000 risk) for a nominal $10 trade. Sizing now
   converts each pair's pip value into USD, so `$10` means `$10`.
2. **JPY-pair SL/TP prices were rounded to 5 decimals** and rejected by OANDA;
   they now use the correct 3-decimal precision.

> ⚠️ Momentum/RSI scalping has no guaranteed edge, spreads and slippage eat
> scalps, and forex leverage amplifies losses. Prove it on the demo account
> first.

---

## Test

```bash
python -m pytest -q
```
