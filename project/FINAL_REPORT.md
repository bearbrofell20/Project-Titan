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

---

## Addendum — JPY-cross trend edge re-audited (and it failed)

Earlier work flagged an EMA 20/60 trend-follow on AUD_JPY + EUR_JPY (H1) as a
candidate (positive across splits with **fixed 30-pip stop / 75-pip target** on
Yahoo H1 data). It was re-run through this stricter harness (realistic next-bar
fills; **ATR-based** stop/target instead of the exact pips it was discovered
with) — `run_jpy_audit.py`:

| slice | expectancy | PF |
|---|---|---|
| all (509 trades) | **−0.008 R** | 0.99 |
| in-sample | +0.021 R | 1.03 |
| validation | −0.187 R | 0.77 |
| out-of-sample | +0.079 R | 1.11 |

Walk-forward: **2 of 6** windows positive. Cost stress: PF 0.93 → 0.85 as costs
rise. Monte Carlo: **P(total > 0) = 45%**.

**Interpretation:** the earlier positive result was **fragile** — it depended on
the specific fixed-pip exit (and on Yahoo's clean synthetic spread). Swap in a
reasonable alternative exit and realistic execution and the edge disappears. A
robust edge survives a change of exit; this one does not. **Classification:
NOT VALIDATED.** The live paper bot is still trading this config on real OANDA
bid/ask — that live run is now the only remaining test, and the prior for it is
weak, not strong. It should be treated as an experiment, not a proven winner.

---

## Addendum — SMC / market-structure stack (ablation) — no edge

Built objective, no-look-ahead engines (`structure.py` swings/BOS/CHOCH with
delayed confirmation; `liquidity.py` prev-day levels + sweep detection) and tested
the classic **liquidity sweep → MSS → retest → entry** stack on EUR/USD M15,
standard 1.5×ATR/2R exits, with component ablation (`run_smc.py`):

| variant | trades | all exp | validation | OOS |
|---|---|---|---|---|
| sweep only | 746 | −0.212 R | −0.135 | −0.266 |
| sweep + MSS | 313 | −0.216 R | −0.511 | −0.242 |
| sweep + MSS + retest | 197 | −0.344 R | −0.642 | −0.842 |

**Every variant negative; each added SMC component makes it worse.** That is
positive evidence the components carry no predictive value (a real edge would
*improve* under confirmation, not degrade). Re-tested with the "purist"
SMC exit — a **structure stop at the swept extreme** and a 2R target off it — and
it is **still negative in every variant and every split** (sweep-only −0.61 R,
sweep+MSS −0.22 R, full stack −0.34 R; all negative IS/VALID/OOS). So the failure
is not the exit. Remaining untested: other pairs, and swing/equal-high liquidity
pools beyond prev-day levels. But across two exit styles and a degrading ablation,
**the SMC entry stack shows no edge on EUR/USD M15.**

---

## Addendum — regime-switching — no edge

Built an objective regime classifier (`regime.py`: Wilder ADX for trend strength,
EMA-slope for direction, ATR-vs-rolling-median for volatility expansion) and tested
whether gating each family to its "ideal" regime beats running it blind
(`run_regime.py`, EUR/USD M15, ATR exits):

| family | unconditional (OOS) | regime-gated (OOS) |
|---|---|---|
| trend → trending | −0.086 | −0.151 (worse) |
| mean-reversion → range | −0.465 | −0.599 (worse) |
| breakout → expansion | −0.221 | −0.286 (worse) |

**Regime-gating improved nothing out-of-sample** — it made every family worse and
cut the sample. The regime hypothesis fails.

## COMPREHENSIVE VERDICT

Tested, honestly and out-of-sample, on real EUR/USD data (plus JPY crosses and
news events): **trend, momentum, breakout, mean-reversion, session filters,
multi-timeframe regime filters, JPY-cross trend, news-reaction (both directions),
the full SMC stack (liquidity sweep → MSS → retest, both exit styles, ablated),
and regime-switching.** Every family is **negative after realistic costs,
out-of-sample.** No individual strategy is profitable, so an ensemble is moot — a
portfolio of negative-expectancy strategies is negative expectancy; combining
losers does not make a winner.

> **FINAL: NO ROBUST EDGE FOUND** across the entire tested strategy universe on
> this data. This is a real, well-evidenced finding — consistent with liquid FX
> being efficient at retail scale — not a tuning failure. Paper trading stays
> disabled; no real capital is justified.
>
> The only avenues genuinely *not* closed here require inputs this environment
> can't supply: true tick/order-flow data, an economic-surprise (actual-vs-forecast)
> feed, or a structural/latency advantage. Each is a different *class* of input,
> not another indicator — and each is already heavily arbitraged by well-resourced
> firms.

## Addendum — key-level reaction (multi-timeframe, scaled to 5m) — no edge

Tested trading the *reaction* at established key levels (previous session / H1 / H4
/ previous-day highs & lows), fading a rejection wick with a stop beyond the wick
and a 2R target (`key_levels.py`, `run_levels.py`):

| timeframe | trades | all exp | PF | OOS |
|---|---|---|---|---|
| M15 (1.6y) | ~4,500 | −0.54 R | 0.49 | −0.62 |
| M5 (120d) | ~2,340 | **−1.18 R** | **0.23** | −1.32 |

Negative at every tolerance and split. **Scaling down to 5m made it dramatically
worse, not better** — the lower timeframe adds noise and the fixed spread eats a
larger share of each smaller move. The result also says price tends to *continue*
through key levels more than it reverses at them (fading loses badly), and
continuation (breakout) was already tested and negative too. No edge in levels.
