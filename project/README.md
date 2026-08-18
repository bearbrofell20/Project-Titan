# EUR/USD M15 Day-Trading Research System

A disciplined harness to answer one question honestly: **does EUR/USD intraday
trading contain a repeatable edge this system can exploit after realistic costs?**

**Current verdict: NO ROBUST EDGE FOUND.** See [`FINAL_REPORT.md`](FINAL_REPORT.md).

## Layout
| module | role |
|---|---|
| `config.py` | typed config (OANDA/strategy/risk/cost); practice by default |
| `data_manager.py` | load/validate M15, resample H4 with completion times (UTC) |
| `indicators.py` | pure, no-look-ahead EMA / Wilder ATR / cross helpers |
| `strategy.py` | baseline signal (H4 regime + M15 EMA cross) and pullback variant |
| `backtester.py` | event loop, next-bar bid/ask fills, ATR stop/trail, costs, day-trade cutoff |
| `risk_manager.py` | 1%-at-stop position sizing; circuit-breaker state |
| `metrics.py` | expectancy (R), PF, Sharpe/Sortino, drawdown, MAE/MFE, streaks |
| `validation.py` | chronological IS/VALID/OOS split + walk-forward |
| `monte_carlo.py` | trade-order bootstrap (return/DD/streak/ruin) |
| `run_backtest.py` | baseline + Part 6 diagnosis |
| `run_validation.py`| pre-registered hypothesis sweep + hostile audit + verdict |
| `run_paper.py` | paper trading — **refuses** until a strategy passes validation |

## Run
```bash
pip install -r requirements.txt
python run_backtest.py     # baseline + diagnosis
python run_validation.py   # hypothesis sweep -> results/experiment_log.csv + verdict
python -m pytest tests/ -q # incl. the non-negotiable no-look-ahead test
```

## Principles enforced
- No look-ahead (automated contamination test must pass).
- Signals act at the **next** bar; fills pay spread + slippage; stop-before-target.
- Selection on a validation slice; the OOS holdout is looked at once.
- Every experiment logged (multiple-testing bias stays visible).
- A negative result is reported as negative — the system never manufactures an edge.

## Data note
Uses ~1.6 years of real OANDA M15 bid/ask (`../market_data/EUR_USD_M15.json`).
3–5 years would be preferable; a live OANDA key + `data_manager` extension would
extend the history. The verdict's sign is stable regardless.
