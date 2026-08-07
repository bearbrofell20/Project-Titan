# Project Titan — strategy audit & validation

A defensible answer to one question: **does the forex bot have a positive edge
after realistic costs?** Built the tooling to measure it honestly, then measured.

## Tooling added
- `data.py` — paginated **bid/mid/ask** history with an on-disk cache
  (`market_data/`, git-ignored). Real per-bar spread, not constants.
- `bt.py` — realistic engine: fills at bid/ask (buy the ask, sell the bid),
  configurable slippage + commission, pluggable exits (fixed / ATR / trailing /
  break-even / time), and gates (spread / ADX regime / UTC session). No
  look-ahead: signal on the close, exit search starts next bar, stop-before-target.
- `fast.py` — O(n) EMA-cross / Donchian / Bollinger signals and Wilder-matching
  ATR/ADX series. Verified bit-identical to the live `oanda_trader` functions.
- `metrics.py` — expectancy (in R), profit factor, Sharpe/Sortino, drawdown,
  streaks, MAE/MFE.
- `validate.py` — pooled multi-pair runs with chronological IS/OOS/holdout,
  walk-forward, and parameter sweeps.

## Data
6 majors (EUR/GBP/JPY/CHF/AUD/CAD vs USD), **~120 days**, M5 (25k bars/pair) and
M15 (10k bars/pair), real bid/ask. Median M5 spread 1.3–1.9 pips.

## Headline results (expectancy in R, net of real spread + 0.3-pip slippage)

Current live strategy — `ema_trend`, fixed 20/40, M5, 6 majors, 630 trades:

| slice | expectancy | PF | win% |
|---|---|---|---|
| all | **−0.158R** | 0.78 | 28% |
| in-sample | −0.170R | 0.77 | 28% |
| out-of-sample | −0.084R | 0.88 | 31% |
| holdout | −0.203R | 0.73 | 27% |

Negative in every split and in 6/6 walk-forward windows; worst losing streak 20.

Swept across **3 strategy families × 2 timeframes × many exits/gates** (trend,
Donchian breakout, Bollinger mean-reversion; M5 & M15; fixed/ATR/trailing/BE/time
exits; session & ADX regime gates). **No configuration was positive across
all + out-of-sample + holdout.** The near-break-even cells flipped sign between
splits — noise, not edge. Parameter-sensitivity confirmed it: expectancy jitters
around zero and changes sign at neighboring parameter values (no stable region).
Even the least-bad config was negative at *zero* slippage and degraded
monotonically as execution costs rose.

## Verdict

**FAILED — we do not have evidence of a positive edge.** On this data these
simple indicator strategies have negative expectancy after realistic costs; the
~1.5-pip spread is a headwind the signals don't overcome. This is a real finding,
not a tuning problem — chasing a better backtest here would be curve-fitting.

## What would change the answer (not yet done)
- A genuine, tested source of edge (e.g. a calibrated predictive feature, an
  event/liquidity effect, or a cost/execution advantage) — indicators alone
  aren't it.
- More history (1–3 years) for regime coverage and walk-forward significance.
- A live **closed-trade ledger** (entry+exit+realized P/L+MAE/MFE+reason) so
  paper trading measures reality, not account NAV (which was corrupted by a demo
  top-up during this work).

Until then the honest stance is: **paper only, no live risk.**
