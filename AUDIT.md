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

## Power check on 1.6 years (update)

Because 120 days can't distinguish a small edge from zero, the candidate set was
re-tested on **~586 days of M15** across the 6 majors (40k bars/pair) — a
pre-registered short list (trend, mean-reversion, Donchian breakout, and
**opening-range breakout** at the London and NY opens), each judged on
all/OOS/holdout expectancy **and** an 8-window walk-forward.

The larger sample pulled every candidate to its true mean — slightly negative
after costs. The best of the entire field, an NY opening-range breakout, came in
at expectancy **+0.005R (all) / −0.018 (OOS) / +0.001 (holdout)**, PF 1.01,
positive in only **3 of 8** walk-forward windows: dead-flat break-even,
indistinguishable from zero and negative once any commission is added. The
120-day "positive OOS" cells did **not** survive.

**Conclusion:** price-only technical/structural strategies on major FX show no
positive edge after realistic costs, at the timeframes and horizon tested. This
is consistent with majors being highly efficient at retail scale. Continuing to
sweep such strategies is data-snooping, not progress. A real edge must come from
a *different, tested* source (a calibrated predictive feature, a cross-asset or
event signal, or a structural/execution advantage) — evaluated on this same
harness with the same all/OOS/holdout + walk-forward discipline.

## Update — the "standard playbook" (Sarwa article) tested

Tested the two ideas from a solid day-trading overview (sarwa.co) not already in
the harness, on the same 6-major real-bid/ask data:

| Strategy | Result (net of costs) |
|---|---|
| MACD(12,26,9) crossover, M5/M15 | −0.06 to −0.10R, negative out-of-sample |
| 5/8/13 EMA-ribbon scalping | −0.11 to −0.22R; worse the more it trades |

Both fail across splits — no robust positive expectancy. Combined with the
earlier sweep, **every strategy in the standard retail playbook** (trend, range,
momentum, breakout, pullback, MACD, MA-ribbon scalping) has now been tested on
major FX net of realistic costs and **none shows an edge**. The high-frequency
ribbon was the worst, confirming that trade frequency mostly buys spread cost.
Edge, if it exists for us, is not in the standard technical playbook.

## Update — championship of the untested families (breakout+retest, squeeze, swing)

Per the $100k rebuild spec, tested the families NOT in the earlier sweep, on 1.6y
M15, 6 majors, real bid/ask + slippage, with ATR-adaptive stops, IS/OOS/holdout +
6-window walk-forward:

| Family | best OOS expectancy | walk-forward+ | verdict |
|---|---|---|---|
| Breakout + retest | −0.045R (HOLD −0.225) | 2/6 | fail |
| Volatility squeeze → expansion | −0.29R | 0/6 | fail |
| Structure swing pullback | −0.20R | 0/6 | fail |

ATR-adaptive stops were *worse* than fixed (tight stops chopped on M15). None met
the spec targets (PF ≥1.30, positive OOS, DD <10%).

**Complete verdict:** the full day-trading strategy space named in the spec —
trend, pullback, breakout, breakout+retest, mean-reversion, momentum, volatility
squeeze, multi-timeframe/structure — has now been tested on 6 major pairs across
M5 and M15, with fixed/ATR/trailing/BE/time exits, regime/session/spread gates,
maximum selectivity, and at costs down to ZERO. **No configuration produces
robust positive out-of-sample expectancy.** At zero cost the best is ~0R: the
signals carry no edge to amplify. Price-technical day-trading of major FX on a
retail account is, on this evidence, not a solvable edge. The remaining honest
forex avenue is a *different signal class* (news/event reaction), which requires
forward data collection to test — it cannot be backtested on price alone.
