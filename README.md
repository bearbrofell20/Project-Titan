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
| `OANDA_RISK_PER_TRADE`   | `10.0`                           | USD risked per trade                      |
| `OANDA_DRY_RUN`          | `false`                          | `true` = log only, submit nothing         |
| `OANDA_ALLOW_LIVE`       | `false`                          | must be `yes` to use the real-money endpoint |
| `OANDA_MAX_OPEN_TRADES`  | `6`                              | cap on concurrent open positions          |

### Safety model

* Defaults to the **practice** endpoint. The live (`fxtrade`) endpoint is
  **refused at startup** unless `OANDA_ALLOW_LIVE=yes` is set explicitly.
* `OANDA_DRY_RUN=true` logs intended orders without sending any.
* One position per instrument and a `MAX_OPEN_TRADES` cap prevent the loop from
  stacking positions every candle.

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
