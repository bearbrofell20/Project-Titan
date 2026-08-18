# EUR/USD M15 Day-Trading — Final Research Report

**Question:** does a statistically defensible, repeatable intraday edge exist on
EUR/USD M15 that this system can exploit after realistic costs?

**One-line answer:** **NO ROBUST EDGE FOUND.**

---

## Data & integrity
- **EUR/USD M15, real OANDA bid/ask**, 40,000 completed bars,
  **2024-12-30 → 2026-08-07 (~1.6 years)**. Median spread 1.6 pips.
  Validation: 0 duplicates, 0 malformed, 3 non-weekend gaps.
- H4 regime candles are **resampled from the same M15** (one real bid/ask source,
  no cross-source leakage), each carrying an explicit completion time.
- **No-look-ahead test PASSES**: mutating all future candles changes **zero**
  earlier signals (`tests/test_no_lookahead.py`). All 10 unit tests pass.
- **Data limitation (stated honestly):** ~1.6 years is below the 3–5 years the
  protocol prefers. The live OANDA token is unavailable in the research
  environment and free sources cap M15 history at ~60 days, so longer M15 history
  could not be obtained here. This limits regime coverage and walk-forward power.
  It does **not** change the sign of the result — everything is negative — but a
  longer sample would tighten the confidence around *how* negative.

## Baseline (Part 5, unchanged as specified)
H4 200-EMA regime + M15 20-EMA cross, 1.5×ATR stop, ATR trailing, 1% risk,
flat before 20:00 UTC.

| metric | value |
|---|---|
| trades | 1,592 |
| win rate | 30.9% |
| profit factor | **0.60** |
| expectancy | **−0.258 R** |
| net | −411 R |
| max drawdown | 414 R |
| worst losing streak | 22 |

**Verdict: decisively unprofitable.**

## Diagnosis (Part 6)
- **The trailing stop is the leak, not the entry.** Trades exited by the ATR
  trailing **stop** averaged −0.34 R (PF 0.51); the minority that survived to the
  **overnight cutoff** averaged +0.41 R (PF 3.6). The stop chops trades on M15
  noise before any move develops.
- Negative in **every session** (Asian −0.34, London −0.24, Overlap −0.21,
  NY −0.16 R) — no session rescues it, though NY is least-bad.
- Negative in **both directions** (long −0.30, short −0.20 R).
- The "overnight survivors are positive" bucket is **survivorship**, not proof of
  entry edge — so it was tested directly as a hypothesis rather than believed.

## Pre-registered hypotheses (Parts 7–10, 23)
Model selection used the **VALIDATION** slice only; the **OOS** holdout is shown
for transparency. Full log: `results/experiment_log.csv`.

| hypothesis | IS exp | VALID exp | VALID PF | OOS exp | trades |
|---|---|---|---|---|---|
| H0 baseline | −0.238 | −0.202 | 0.68 | −0.363 | 1592 |
| H1 no-trail, hold to cutoff | −0.283 | −0.281 | 0.71 | −0.274 | 1064 |
| H2 fixed 2R target, no trail | −0.235 | −0.283 | 0.64 | −0.355 | 1364 |
| H3 break-even @1R + trail | −0.245 | −0.208 | 0.68 | −0.336 | 1590 |
| H4 NY+overlap session only | −0.200 | −0.188 | 0.64 | −0.160 | 607 |
| H5 pullback-to-EMA, hold | −0.374 | −0.216 | 0.78 | −0.230 | 898 |
| H6 wider 2×ATR stop, hold | −0.240 | **−0.186** | 0.78 | −0.220 | 902 |

**Every hypothesis is negative in in-sample, validation, AND out-of-sample.** The
best on validation (H6) is still −0.186 R. **Nothing qualified to advance to the
hostile audit** (walk-forward / cost-stress / Monte-Carlo), because a strategy
that is negative on the validation slice has already failed.

## Hostile audit questions (Part 26)
- *Could this be random / curve-fit / a data leak?* The result is negative, so
  there is no positive result to explain away. No-look-ahead passes.
- *Does any parameter/session/exit save it?* No — the whole neighbourhood is
  negative; fixing the diagnosed exit problem (H1/H6) reduced the bleed but never
  crossed zero.
- Costs were not even the deciding factor — the strategy is negative on gross
  behaviour; realistic spread only deepens it.

## FINAL VERDICT

> **NO ROBUST EDGE FOUND.**

On ~1.6 years of real EUR/USD M15 bid/ask, the specified baseline and every
pre-registered variant have **negative expectancy in-sample, in validation, and
out-of-sample**, after realistic costs. This is consistent with EUR/USD being
highly efficient at retail scale and with this project's prior findings across
M5/M15/H1. Per the protocol, **paper trading is NOT enabled** (`run_paper.py`
refuses to start). Forcing a positive result from here would be curve-fitting.

**What could still change the answer (not attempted here):** a genuinely different
*signal class* (calibrated event/news reaction, order-flow, cross-asset), or a
longer 3–5 year M15 sample via a live OANDA key — each tested on this same
harness with the same OOS discipline. Price-only indicator day-trading of EUR/USD
is not, on this evidence, a solvable edge.
