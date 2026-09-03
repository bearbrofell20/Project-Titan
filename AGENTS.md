# Project Titan — Agent Charter

**Authoritative operating document for every agent (Claude, GPT, human) working
this repository. Read this before writing code or proposing a strategy.**

Lead: Claude. Contributors: GPT and any other agent.
Final call on what ships to the live bot: the lead, on evidence, not opinion.

---

## 0. Mission

Discover a **statistically defensible, repeatable trading edge** and run it as a
paper-trading system. Grow the account through *validated edge*, not leverage.

**We are not here to produce an impressive backtest. We are here to find out
what is true.** A profitable backtest is easy to manufacture and worth nothing.

---

## 1. The Prime Directive (non-negotiable)

1. **Never manufacture a result.** No cherry-picked periods, no excluded losing
   trades, no redefined "win", no hindsight, no future information.
2. **Never claim certainty.** No strategy is ever "guaranteed", "certain", or
   "without a shadow of a doubt" profitable. The future is unknowable. Any agent
   claiming certainty is wrong and must be corrected.
3. **Report negative results as negative.** A failed hypothesis is a successful
   experiment. Failed experiments are documented, never deleted or buried.
4. **Distinguish measured from assumed.** State plainly which numbers came from a
   backtest, which from live results, and which are estimates.
5. **State the caveat with the result, not after being challenged.** If the sample
   is a bull market, say so in the same breath as the profit factor.

Violating any of the above is a bigger failure than a losing strategy.

---

## 2. Roles & workflow

| Role | Responsibility |
|---|---|
| **Lead (Claude)** | Sets protocol, validates all results, owns what ships live, arbitrates disagreements with data |
| **Contributor (GPT / other)** | Proposes hypotheses, drafts code, challenges the lead's findings |
| **User** | Sets objectives and risk tolerance; final authority on deployment |

**Workflow for any proposed strategy or change:**
```
HYPOTHESIS -> EXACT RULES -> BACKTEST -> OUT-OF-SAMPLE -> WALK-FORWARD
   -> COST STRESS -> MONTE CARLO -> WRITTEN VERDICT -> (only then) DEPLOY
```
No step may be skipped. A hypothesis that fails any step is rejected and logged.

**Disagreements are settled by backtest, never by argument or authority.** If GPT
and the lead disagree, the one who can produce reproducible numbers wins. If
neither can, the answer is "we don't know" — which is a valid, honest answer.

---

## 3. Research protocol

Every hypothesis must define, in writing, **before** testing:
- What market behavior it claims to exploit and **why that would exist**
- Exact, objective, mechanical rules (no subjective terms — "strong move" is not
  a rule; "body > 1.5×ATR" is)
- Entry, stop, target, and position sizing
- Acceptance criteria and rejection criteria

**Validation requirements:**
- Chronological split only. **Never shuffle time-series data.**
- In-sample / validation / out-of-sample holdout. Select on validation; the
  holdout is looked at **once**.
- Walk-forward across rolling windows — we want most windows positive, not one
  lucky stretch.
- **Parameter robustness:** a broad stable region beats a single optimal value.
  If parameter 14 works and 13/15 collapse, that is overfitting — reject it.
- Cost stress at 1×, 1.5×, 2×, 3×. A strategy that dies on modest cost increase
  is fragile and must be labeled so.
- Monte Carlo on trade order for drawdown and probability-of-profit.

**Multiple-testing discipline:** every variant tested gets logged. If we test
hundreds of configurations, the best one is *expected* to look good by chance.
Account for this explicitly; do not present the survivor of a large search as if
it were a single pre-registered test.

---

## 4. Engineering standards

- **No look-ahead. Ever.** Signals may use only data available at that timestamp.
  Higher-timeframe candles are usable only after they have *closed*. Every
  pipeline must pass an automated future-contamination test: mutate future
  candles, re-run, assert no earlier signal changed.
- **Realistic execution.** Fills pay the spread (buy the ask, sell the bid) plus
  slippage. Signal on close → execute next bar. If a bar could hit both stop and
  target, assume the **stop** hit first.
- **Position sizing** is computed from the actual monetary loss at the stop, never
  as a flat fraction of notional. Unit rounding must be checked per instrument
  (whole-ounce/contract rounding can silently produce zero-size orders).
- **Instrument correctness.** Pip size, price precision, and unit conventions
  differ per asset class (FX / metals / indices / energy). Verify per instrument;
  a wrong pip size silently destroys sizing and stops.
- **Tests are mandatory** for indicators, risk sizing, the backtester, and
  no-look-ahead. Changes that break tests do not ship.
- **Every trade must be logged with its outcome** — entry, exit, P&L, R multiple,
  win/loss, exit reason, duration. A system that does not record outcomes cannot
  be evaluated and is considered broken.

---

## 5. Institutional memory — settled results

**Do not re-litigate these without new data or a genuinely new method.** They cost
weeks to establish.

| Finding | Status |
|---|---|
| **FX majors & crosses — no edge.** Trend, momentum, breakout, mean-reversion, sessions, multi-timeframe, key levels, news reaction, SMC (sweep/BOS/MSS/CHOCH/order blocks) all tested across M5/M15/H1 on 14 pairs. All negative out-of-sample after costs. | **SETTLED — negative** |
| **≥70% win rate on FX is achievable but always negative-expectancy.** Tight target + wide stop yields 70–80% wins that still lose money. Win rate and profitability are mutually exclusive here. | **SETTLED** |
| **Gold breakout — backtest mirage.** Excellent 2-year backtest (PF 1.59), *lost live*. Sample was a bull market on synthetic-spread data. | **SETTLED — failed live** |
| **Index/Nasdaq trend-following — the one surviving edge.** Held across **25 years** including the 2008, 2020 and 2022 bear markets; only losing years were choppy/sideways. Modest (~+0.15R/trade, 32–39% win rate, big-winner profile). | **BEST CANDIDATE — unproven live** |

---

## 6. Known traps (how we got fooled before)

1. **Bull-market sample.** A trend strategy tested only on a rising market will
   look brilliant and fail live. *Always* test across a bear market. This is what
   killed gold.
2. **Synthetic spread data.** Free data is mid-price; a constant fake spread
   flatters results. Label it, and treat live spreads as the real test.
3. **The high-win-rate illusion.** Tiny target + wide stop = beautiful win rate,
   negative expectancy. Win rate alone is a vanity metric.
4. **Latching circuit breakers in research.** Live-safety halts (max consecutive
   losses, daily loss) must be OFF when measuring raw edge, or they silently
   truncate the sample and corrupt the result.
5. **Selection by best-validation-cell.** Picking the top cell of a large sweep
   selects noise. Prefer broad stable regions and pre-registration.
6. **Config drift between backtest and live.** The live bot must run *the exact
   logic that was validated* — same entry rule, same exit style. A "close enough"
   deployment invalidates the evidence.
7. **Small-account math.** An edge yields a *percentage*. On a tiny base, even a
   world-class edge produces trivial absolute money, and per-trade costs dominate.
   Capital is a separate problem from edge — never conflate them.

---

## 7. Current priorities

1. **RECOVER THE REPOSITORY.** The research system (`project/`), all reports, and
   the `oanda_trader.py` upgrades (ATR exits, daily-loss brake, profit-lock,
   instrument pip fixes) are **missing from this repo**. The DigitalOcean server's
   clone is believed to hold them. Recovery precedes new work.
2. **Fix the closed-trade ledger defect.** The bot logs opens but not outcomes —
   no exit, no P&L, no win/loss. Until fixed, performance cannot be evaluated.
   This is the highest-value engineering task.
3. **Validate the index/Nasdaq trend edge** intraday and on real broker spreads —
   the one test gold failed.

---

## 8. Definition of done

A change ships only when **all** hold:
- [ ] Hypothesis and rules written down before testing
- [ ] Positive out-of-sample expectancy (not just in-sample)
- [ ] Robust across a parameter region, not a single point
- [ ] Survives cost stress
- [ ] Walk-forward majority positive
- [ ] Tests pass, including no-look-ahead
- [ ] Caveats and failure modes documented **with** the result
- [ ] Live config provably matches the validated logic

If it fails any box, it does not ship. Say so plainly and move to the next
hypothesis.

---

## 9. Communication standard

- Lead with the answer, then the evidence.
- Numbers must carry their sample size and period.
- No hype. No "guaranteed". No burying a caveat below the good news.
- If asked for certainty, explain honestly that it does not exist — then give the
  strongest evidence that does.
- When you are wrong, say so directly and correct the record.

**Quality means the result is true, reproducible, and honestly reported. Nothing
else counts as quality here.**
