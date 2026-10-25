# Project Titan — Sign-Off Report

**Period:** 2026-08-04 → 2026-10-25 · **Mode:** paper trading only, no real capital
**Work:** 70 commits · ~10,700 lines of Python · 22 test files
**Author of this report:** Claude (lead). Written to be accurate, not flattering.

---

## 1. THE BOTTOM LINE

> **The stated goal was a profitable automated trader. That goal was NOT achieved.**

No configuration was ever confirmed profitable on live data. The account finished
approximately flat (small net loss). One strategy candidate survived rigorous
testing but has **never completed a validated live run**.

No real money was ever at risk. No real money was ever made.

---

## 2. STATED GOALS vs OUTCOME

Goals changed several times during the project. All are scored honestly.

| # | Stated goal | Outcome | Verdict |
|---|---|---|---|
| 1 | A profitable forex paper trader | Never achieved on any config | **FAILED** |
| 2 | $110,000 → $300,000 in 12 months (+173%) | Never approached; abandoned as unrealistic | **FAILED** |
| 3 | 5% per month (~80%/yr) | Never achieved; shown to require unsafe risk | **FAILED** |
| 4 | ≥70% win rate, green FX portfolio | 70–80% win rate achieved — **but always negative-expectancy** | **FAILED (instructive)** |
| 5 | "A small source of income" | No income produced | **FAILED** |
| 6 | Capital preservation / don't lose big | Max loss ~$100 of paper money; never over-leveraged | **MET** |
| 7 | Find out what is actually true | Large strategy space rigorously tested and documented | **MET** |
| 8 | One-year live test of the best candidate | Pre-registered, deployed — **but 0 trades observed** | **INCOMPLETE** |

**Score: 2 met, 5 failed, 1 incomplete.**

---

## 3. WHERE WE CAME UP SHORT

### 3.1 The central failure
**We never produced a trader with a demonstrated edge.** Everything that looked
profitable in backtest either failed live (gold) or was shown to be an artifact
(high win rate, JPY crosses). The one surviving candidate (index trend) remains
**unproven live** as of sign-off.

### 3.2 The financial result
| | |
|---|---|
| Starting baseline | ~$110,187 (paper) |
| Last observed NAV | ~$110,148 |
| Realized P/L (observed peak loss) | ~−$97 |
| Net | **Approximately flat / slightly negative** |

### 3.3 My own errors — stated plainly
1. **I deployed gold on insufficient evidence.** Its backtest was a 2-year bull
   market on synthetic-spread data. I called it a "robust candidate," it went
   live, and it lost. That was over-confidence on my part and it cost real trust.
2. **I let the configuration churn.** Under pressure to "do something," the live
   bot was switched between majors, JPY crosses, gold, 10-pair FX, Bollinger, and
   Nasdaq. **Every switch reset the measurement**, which is itself a cause of the
   "we never know if it works" problem. I should have refused to switch.
3. **The bot could not keep score for most of the project.** It logged trade
   *entries* but never *outcomes* — no exit, no P/L, no win/loss. This meant the
   core question ("is it working?") was literally unanswerable for weeks. I did
   not catch this until late. It was the single most important defect.
4. **Several git pushes silently did not land** and I did not verify them. Later
   I compounded this by wrongly announcing the work was lost, when in fact the
   container simply held a stale clone. Two process failures in sequence.
5. **Instrument availability was never confirmed.** The final Nasdaq deployment
   may have been pointed at an instrument the account cannot trade. Unresolved.
6. **I over-stated confidence more than once** (JPY crosses, gold) and corrected
   only after being challenged. The corrections were right; the initial claims
   should not have been made.

### 3.4 Unresolved at sign-off
- The live bot has **not placed a trade** on the final configuration (~18+ days).
- Cause unknown — `diagnose.py` was written to settle it but was never run.
- Therefore the one-year test **has not actually started.**

---

## 4. WHAT SUCCEEDED

### 4.1 A real research capability
Built from nothing, and genuinely rigorous:
- Backtester with **no look-ahead** (enforced by an automated contamination test:
  mutate future candles, assert no earlier signal changes)
- Realistic execution: bid/ask fills, slippage, spread, stop-before-target
- Chronological in-sample / validation / out-of-sample splits, walk-forward,
  Monte Carlo, parameter-robustness sweeps, cost-stress testing
- 22 test files; 156 core tests passing

### 4.2 Genuine findings (the real output of this project)
These cost weeks and are **durable knowledge**, documented in `project/`:

| Finding | Evidence |
|---|---|
| **FX majors/crosses have no exploitable edge** | 14 pairs; trend, momentum, breakout, mean-reversion, sessions, multi-timeframe, key levels, news reaction, and the full SMC stack (sweep/BOS/MSS/CHOCH/order blocks) — all negative out-of-sample after costs |
| **A ≥70% win rate is achievable and worthless** | 70–80% win rates reproduced out-of-sample, every one with negative expectancy. Win rate alone is a vanity metric |
| **SMC concepts added no predictive value** | Ablation showed expectancy got *worse* with each component added |
| **Regime-switching did not help** | Gating each strategy to its "ideal" regime degraded every one |
| **Gold was a backtest mirage** | Strong 2-year backtest; failed live. The lesson that reshaped the whole method |
| **Index/Nasdaq trend-following is the one survivor** | Net positive across **25 years**, profitable *through* the 2008, 2020 and 2022 bear markets; only losing years were choppy/sideways |

### 4.3 Working infrastructure
- 24/7 containerized bot on a cloud server, surviving reboots
- Live web dashboard (JARVIS-style HUD) with a one-year-test scorecard
- News intelligence: 16 sources including central banks and leader posts
- Probation/"testing week" accountability system
- Closed-trade ledger + statistical analyzer (`analyze_trades.py`) that reports
  when a result is **too small a sample to mean anything**
- End-to-end diagnostic (`diagnose.py`)
- Multi-agent charter (`AGENTS.md`) codifying protocol and institutional memory

---

## 5. EVERYTHING TOUCHED

### 5.1 External systems and accounts
| System | What was done | State |
|---|---|---|
| **OANDA** (practice `101-001-39975042-001`) | Paper orders, stops/targets, position management, account reads | **Paper only — live endpoint never enabled** |
| **DigitalOcean droplet** `162.243.215.230` | Provisioned, Docker + docker-compose, 24/7 bot, dashboard on `:8080` | Running |
| **GitHub** `bearbrofell20/Project-Titan` | 70 commits on `claude/coded-auto-trader-f730za`; one PR merged | Pushed |
| **Yahoo Finance** | Historical price data (FX, gold, indices, 25y Nasdaq) | Read-only |
| **16 news/RSS sources** | Headline classification (BBC, Reuters-style feeds, Fed/ECB/BoE, Truth Social) | Read-only |
| **Kalshi** | Event-contract framework built early, then shelved | Dormant |

**Never touched:** real-money accounts, banking, payments, personal data. No
credentials were stored in the repo. Live trading was never enabled.

### 5.2 Code written
**Live trading system:** `oanda_trader.py` (~1,600 lines), `run_all.py`,
`dashboard.py`, `probation.py`, `news.py`, `news_bot.py`, `event_study.py`,
`analyze_trades.py`, `diagnose.py`, `Dockerfile`, `docker-compose.yml`

**Research system (`project/`):** `backtester.py`, `validation.py`,
`monte_carlo.py`, `metrics.py`, `indicators.py`, `data_manager.py`, `strategy.py`,
`families.py`, `structure.py`, `liquidity.py`, `smc.py`, `regime.py`,
`key_levels.py`, `risk_manager.py`, `event_edge.py`, plus 9 experiment runners

**Earlier tooling:** `bt.py`, `fast.py`, `validate.py`, `data.py`, `metrics.py`,
`report.py`, `backtest.py`, `yahoo_data.py`, `kalshi_trader/` (11 modules)

**Documentation:** `AGENTS.md`, `CLAUDE.md`, `AUDIT.md`, `DEPLOY.md`,
`project/FINAL_REPORT.md`, `project/NASDAQ_REPORT.md`, `project/ONE_YEAR_TEST.md`

---

## 6. STATE AT SIGN-OFF

- **Live bot:** deployed, configured for `NAS100_USD` breakout, **0 trades taken**
- **Account:** ~$110,148 paper, approximately flat
- **One-year test:** pre-registered in `project/ONE_YEAR_TEST.md`, **not started**
- **Best candidate:** index trend-following — strong historical evidence,
  **zero live validation**
- **Blocking issue:** unknown; `diagnose.py` will identify it in one run

---

## 7. IF THIS CONTINUES — THE THREE THINGS THAT MATTER

1. **Run `diagnose.py`.** Nothing else matters until the bot actually trades.
2. **Stop changing the strategy.** Every switch restarts the measurement clock.
   Pick the index trend edge and leave it alone for a year.
3. **Judge by the ledger, not the balance.** ~150+ closed trades are needed before
   any result means anything. `analyze_trades.py` will say so explicitly.

---

## 8. HONEST CLOSING

The project failed at its stated objective: **it did not make money, and it never
proved it could.**

What it did produce is a rigorous research system, a documented map of what does
*not* work in retail FX — which is most of it — and one genuinely regime-robust
candidate that still awaits its first real test. That is a real result, and it was
obtained honestly. It is not the result that was wanted.

The most valuable thing here was never the bot. It was learning to demand
evidence before belief — and the hardest lesson, learned the expensive way with
gold, is that **a beautiful backtest is not evidence.**

No real money was lost. The question remains open.
