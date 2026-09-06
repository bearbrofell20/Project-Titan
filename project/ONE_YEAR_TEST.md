# Project Titan — The One-Year Test (pre-registered)

**Registered:** 2026-09-06 · **Judged:** 2027-09-06 · **Model:** `MODEL_v1`

This document is written **before** the test begins so that success and failure
are defined by evidence rather than by whatever we feel when we see the number.
Per `AGENTS.md` §1, criteria set here may not be loosened later to make a result
look better. Changing the strategy mid-flight ends this test and starts a new one
under a new model version.

---

## 1. Hypothesis

> The index trend-following (breakout) edge — measured at **+0.15 R/trade** and
> shown to hold across **25 years including the 2008, 2020 and 2022 bear
> markets** — persists on live broker data with real spreads.

**Why it should exist:** equity indices trend and exhibit momentum persistence;
breakouts capture regime shifts. Unlike FX (efficient, mean-reverting, settled
negative), index trends are driven by sustained capital flows.

**What would falsify it:** live expectancy at or below zero over a large sample,
or a collapse in a non-trending regime beyond what the 25-year record showed.

---

## 2. What is being tested (fixed for the duration)

| Parameter | Value |
|---|---|
| Instrument | Index (NAS100_USD) — **no gold, no FX** |
| Strategy | Donchian breakout, lookback 40 |
| Exits | ATR-scaled: 1.5×ATR stop, 2R target |
| Timeframe | H1 |
| Risk / trade | **1% of equity** |
| Starting equity | $110,000 (paper) |
| Expected trades | ~228 (≈19/month) |

Excluded by prior evidence (`AGENTS.md` §5): FX majors/crosses (no edge), gold
(failed live), high-win-rate configs (negative expectancy).

---

## 3. Pre-registered expectations

| | value |
|---|---|
| Expected P/L | **+$37,600 (+34%)** |
| 95% range | **−$4,700 to +$79,900** |
| Expectancy CI after 1 yr | −0.019 to +0.319 R — **still includes zero** |
| Trades for true confirmation | ~589 (~2.6 years) |

**A year gives a strong indication, not proof.** This is stated up front so that
an inconclusive result is not mistaken for failure, nor a good one for certainty.

---

## 4. Verdict criteria (judged at 12 months)

**PASS** — continue and consider scaling:
- Expectancy > 0, **and**
- ≥150 closed trades, **and**
- Profit factor ≥ 1.15, **and**
- Max drawdown < 20%

**INCONCLUSIVE** — continue unchanged, do not scale:
- Expectancy > 0 but the 95% CI straddles zero (the *expected* outcome)

**FAIL** — stop; return to research:
- 95% CI entirely below zero, **or**
- Max drawdown ≥ 25%, **or**
- Live expectancy materially below backtest with no execution explanation

---

## 5. Rules of conduct during the test

- **Do not change the strategy** to chase results. Any change = `MODEL_v2` and a
  fresh clock.
- **Do not read short-term P/L as signal.** At n<100 trades the result is noise;
  `analyze_trades.py` will say so explicitly.
- **Monthly:** record the scorecard. Record only — no decisions.
- **Quarterly:** review drawdown and execution quality (slippage, fills, sizing).
- **Decisions happen at 12 months**, against §4.

### Permitted mid-flight interventions (bugs, not opinions)
1. Max drawdown ≥ 25% → halt and review.
2. Execution defects — wrong sizing, wrong instrument, look-ahead, zero-unit
   orders — fixed immediately. These are bugs, not strategy changes.
3. Broker/data outages → pause, document the gap.

---

## 6. How it will be judged

`analyze_trades.py` against `trade_logs/closed_trades.jsonl`: Wilson CI on win
rate, bootstrap CI on expectancy, and the sample size required for significance.
The verdict is whatever that output says — including "inconclusive."

**The purpose of this year is to learn the truth, not to be right.**
