# Project Titan — Kalshi Auto Trader

A small, safety-first automated trading bot for the
[Kalshi](https://kalshi.com) event-contracts exchange, written in Python.

It fetches live markets, runs a pluggable strategy over them, gates every
proposed trade through hard risk limits, and then either **logs** the trade
(dry-run, the default) or submits it to Kalshi (live). Everything that matters —
strategies, risk, order modelling — is pure Python with unit tests and needs no
network or credentials to run.

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

## Test

```bash
python -m pytest -q
```
