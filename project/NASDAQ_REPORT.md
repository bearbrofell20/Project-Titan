# Nasdaq (NAS100) Breakout — Research Report

Prepared for review and cross-examination. Data: NQ futures H1, ~2.4 years
(2024-04 → 2026-08), 13,707 bars, Yahoo mid + synthetic spread. Strategy: Donchian
breakout (enter on a break of the last N-hour range), 1.5×ATR stop, 2R target.

## Bottom line

Nasdaq breakout is a **legitimate backtest candidate** — but it is the **same
profile as gold, which just lost you money live.** Read this as "promising but
unproven and risky," not "the fix."

## ⚠️ The gold warning (read first)

Gold backtested positive and **lost in live paper trading.** Why that matters here:
Nasdaq shares gold's three weaknesses exactly —
1. **Tested in a raging bull market** (Nasdaq ~doubled 2024–2026). Breakout feasts
   in strong uptrends; we have almost no bear/range data to prove it survives one.
2. **Synthetic-spread futures data**, not real OANDA NAS100 bid/ask.
3. It's a **trend strategy** — great while the trend runs, painful when it chops.

So the honest prior: Nasdaq could disappoint live the same way gold did.

## The numbers (flagship: breakout-40, 1.5×ATR / 2R)

| metric | value | read |
|---|---|---|
| Trades | 546 | good sample |
| **Win rate** | **39%** | **LOW — you lose 61% of trades** |
| Avg winner | +1.98 R | big |
| Avg loser | −1.02 R | controlled |
| Expectancy | +0.149 R | positive |
| Profit factor | 1.24 | modest-positive |
| Max drawdown | 25 R | meaningful |
| Worst losing streak | **12 in a row** | brutal to watch |
| Sharpe / Sortino | 2.38 / 7.0 | strong |

**The math works through big winners, not frequent wins.** This is the OPPOSITE of
the 70%-win-rate FX bot you wanted. It wins ~4 of every 10 trades and can lose 12
straight before a big winner pays for them all. If watching red stresses you, this
strategy is psychologically hard even when it's profitable.

## Robustness (the encouraging part)

- **Parameters:** lookback 20–60 all positive (+0.145 to +0.196 R) — a stable
  region, not a lucky point.
- **Out-of-sample:** IS +0.19, **VALIDATION −0.00 (flat)**, OOS +0.16. The flat
  validation slice is a yellow flag — weaker consistency than gold showed.
- **Cost stress:** +0.149 → +0.085 R even at 3× spread + heavy slippage. Not
  cost-fragile (Nasdaq moves dwarf the spread).
- **Long +0.13 / Short +0.18** — both sides work, not a one-way artifact.
- **Sessions:** positive in all (Asian strongest +0.23, London weakest +0.04).
- **Monte Carlo:** P(total > 0) = 99.1%, 5th-percentile +24 R.

## Honest concerns

1. **39% win rate** — clashes hard with your stated goal of a high-win, consistently
   green feel. You'd be red most days between big winners.
2. **Flat validation slice** — the edge isn't uniform across all sub-periods.
3. **Bull-market sample + synthetic data** — the exact combo that made gold look
   good and then fail live.
4. **Live ≠ backtest** — proven by gold, one week ago.

## What it would take to trust it

- **Live paper trading on real OANDA NAS100 bid/ask** for several weeks (the one
  test gold failed).
- A stretch of **non-trending / down** Nasdaq to see it survive a regime change.
- Real spreads confirmed (OANDA index spreads widen at the cash open/close).

## Recommendation

**Do NOT bet the account on it, and do NOT read the 99% Monte-Carlo as a promise —
gold had great backtest numbers too.** If you want to test it, the only honest way
is a **small live paper allocation alongside** whatever else you run, judged over
weeks on *real* spreads — treating it as an experiment with a real chance of
failing, exactly as gold did. It is a candidate, not a paycheck.

**One-line verdict:** genuine edge in the backtest, real robustness signals, but a
low-win-rate trend strategy carrying the identical "bull-market + synthetic data"
risk that just burned gold — promising, unproven, and not a safe income source.

## UPDATE — 25-year multi-regime test (the decisive one)

Tested a DAILY breakout on 25 years of Nasdaq (^NDX, 2001–2026) to answer the
one question that killed gold: does the trend edge survive bear markets?

- **Full 25y: net positive, PF 1.25, +0.186 R/trade** (breakout-40, 2×ATR/3R).
- **It made money THROUGH the crashes:** 2008 +3.1R, 2020 +3.7R, 2022 +0.9R.
- Only losing years were **choppy/sideways** (2011 −8R, 2015 −5R) — trend-following's
  known weakness, not a crash.
- Parameter-robust across lookback 20/40/60 (+0.12 to +0.20 R).

**Significance:** unlike gold (2-year bull-market sample), the Nasdaq trend edge
holds across 25 years and every major regime, long and short. Caveats remain
(daily ≠ the intraday config; ~7 trades/yr is thin; modest ~1.2R/yr; 32% win rate).
But this is the strongest regime-robustness evidence in the project — the trend
edge on Nasdaq is real, not a bull-market artifact. Still not "certain" (nothing
is), but a genuinely different tier of evidence.
