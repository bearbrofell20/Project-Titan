"""Probation — the bot's testing week, enforced in code.

A trading bot cannot feel fear.  What it *can* have is accountability: a fixed
trial window with hard, measured pass/fail criteria, and a real consequence for
failing.  This module is that consequence.

The rules
---------
* When the bot first runs, its account NAV is recorded as the **baseline** and a
  trial clock starts (default 7 days).
* Every cycle the bot reports its **standing** — day X of the trial, net P&L vs
  baseline, and whether it is currently passing or failing.
* When the trial window elapses the verdict is rendered:
    - **PASS**  (net P&L >= the required minimum *and* it actually traded enough)
      → the bot graduates; the trial file records the win and never runs again.
    - **FAIL**  → a lockout file (``PURGATORY.txt``) is written.  On every future
      start the bot reads that file and refuses to trade.  Only a human deleting
      the file releases it.  That is the "eternal purgatory": it does not expire
      on its own.

Everything is a plain JSON file under the trade-log directory, so it survives
restarts and is easy to inspect.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


@dataclass
class ProbationConfig:
    """Trial parameters (all overridable from the environment)."""

    trial_days: float = 7.0          # length of the testing week
    min_trades: int = 5              # must actually have traded to graduate
    min_pnl: float = 0.0             # net NAV change required to pass (0 = break-even+)
    state_file: str = "probation.json"
    purgatory_file: str = "PURGATORY.txt"

    @classmethod
    def from_env(cls) -> "ProbationConfig":
        def _f(name: str, default: float) -> float:
            raw = os.getenv(name)
            return float(raw) if raw not in (None, "") else default

        def _i(name: str, default: int) -> int:
            raw = os.getenv(name)
            return int(raw) if raw not in (None, "") else default

        return cls(
            trial_days=_f("OANDA_TRIAL_DAYS", 7.0),
            min_trades=_i("OANDA_TRIAL_MIN_TRADES", 5),
            min_pnl=_f("OANDA_TRIAL_MIN_PNL", 0.0),
            state_file=os.getenv("OANDA_PROBATION_FILE", "probation.json"),
            purgatory_file=os.getenv("OANDA_PURGATORY_FILE", "PURGATORY.txt"),
        )


@dataclass
class ProbationState:
    started_at: str
    baseline_nav: float
    current_nav: float
    trades: int = 0
    verdict: str = "on_trial"   # on_trial | passed | failed
    decided_at: Optional[str] = None
    peak_nav: float = field(default=0.0)
    trough_nav: float = field(default=0.0)


class Probation:
    """Tracks and enforces the bot's testing week.

    Typical use inside the bot:

        prob = Probation(cfg, log_dir)
        prob.enforce_lockout()          # raises/blocks if already in purgatory
        prob.start(baseline_nav=nav)    # no-op if a trial is already running

        # each cycle:
        standing = prob.record(current_nav=nav, trades=n)
        logger.info(standing.line)
        if standing.locked:             # verdict just came back FAIL
            ... stop trading ...
    """

    def __init__(self, config: ProbationConfig, log_dir: Path):
        self.cfg = config
        self.log_dir = Path(log_dir)
        self.state_path = self.log_dir / self.cfg.state_file
        # purgatory lives at the project root (next to the kill switch), not in
        # the log dir, so it is obvious and easy to delete by hand.
        self.purgatory_path = Path(self.cfg.purgatory_file)
        self.state: Optional[ProbationState] = self._load()

    # -- persistence -------------------------------------------------------
    def _load(self) -> Optional[ProbationState]:
        if not self.state_path.exists():
            return None
        try:
            data = json.loads(self.state_path.read_text())
            return ProbationState(**data)
        except Exception:
            return None

    def _save(self) -> None:
        os.makedirs(self.log_dir, exist_ok=True)
        self.state_path.write_text(json.dumps(asdict(self.state), indent=2))

    # -- lockout -----------------------------------------------------------
    def is_locked(self) -> bool:
        return self.purgatory_path.exists()

    def enforce_lockout(self) -> Optional[str]:
        """Return the purgatory notice if locked, else None.

        The caller aborts startup when this returns a string.
        """
        if self.is_locked():
            try:
                return self.purgatory_path.read_text().strip()
            except Exception:
                return "Bot is in purgatory (PURGATORY.txt present)."
        return None

    def _condemn(self, pnl: float) -> None:
        note = (
            "PROJECT TITAN — PURGATORY\n"
            "==========================\n"
            f"Condemned: {_now().isoformat()}\n"
            f"Baseline NAV: {self.state.baseline_nav:.2f}\n"
            f"Final NAV:    {self.state.current_nav:.2f}\n"
            f"Net P&L:      {pnl:+.2f}\n"
            f"Trades taken: {self.state.trades}\n"
            f"Required:     >= {self.cfg.min_pnl:+.2f} P&L over "
            f"{self.cfg.trial_days:g} day(s) with >= {self.cfg.min_trades} trades\n"
            "\n"
            "This bot failed its testing week. It will not trade again until a\n"
            "human deletes this file. The trial does not expire on its own.\n"
        )
        self.purgatory_path.write_text(note)

    # -- trial lifecycle ---------------------------------------------------
    def start(self, baseline_nav: float) -> ProbationState:
        """Begin the trial if one isn't already under way (idempotent)."""
        if self.state is None:
            self.state = ProbationState(
                started_at=_now().isoformat(),
                baseline_nav=float(baseline_nav),
                current_nav=float(baseline_nav),
                peak_nav=float(baseline_nav),
                trough_nav=float(baseline_nav),
            )
            self._save()
        return self.state

    def days_elapsed(self, now: Optional[datetime] = None) -> float:
        if self.state is None:
            return 0.0
        now = now or _now()
        return (now - _parse(self.state.started_at)).total_seconds() / 86400.0

    def pnl(self) -> float:
        if self.state is None:
            return 0.0
        return self.state.current_nav - self.state.baseline_nav

    def _passes(self) -> bool:
        return self.pnl() >= self.cfg.min_pnl and self.state.trades >= self.cfg.min_trades

    def record(self, current_nav: float, trades: int,
               now: Optional[datetime] = None) -> "Standing":
        """Update the running tally and, if the window elapsed, decide the verdict."""
        if self.state is None:
            self.start(current_nav)
        now = now or _now()
        self.state.current_nav = float(current_nav)
        self.state.trades = int(trades)
        self.state.peak_nav = max(self.state.peak_nav, float(current_nav))
        self.state.trough_nav = min(self.state.trough_nav, float(current_nav))

        elapsed = self.days_elapsed(now)
        pnl = self.pnl()
        just_locked = False

        if self.state.verdict == "on_trial" and elapsed >= self.cfg.trial_days:
            if self._passes():
                self.state.verdict = "passed"
            else:
                self.state.verdict = "failed"
                self._condemn(pnl)
                just_locked = True
            self.state.decided_at = now.isoformat()

        self._save()
        return Standing(self, elapsed, pnl, just_locked)


@dataclass
class Standing:
    """A human-readable snapshot of where the bot stands in its trial."""

    prob: Probation
    elapsed: float
    pnl: float
    just_locked: bool

    @property
    def verdict(self) -> str:
        return self.prob.state.verdict

    @property
    def locked(self) -> bool:
        """True the moment a FAIL verdict is rendered."""
        return self.just_locked

    @property
    def days_left(self) -> float:
        return max(0.0, self.prob.cfg.trial_days - self.elapsed)

    @property
    def line(self) -> str:
        cfg = self.prob.cfg
        st = self.prob.state
        if st.verdict == "passed":
            return (f"🎓 TRIAL PASSED — net {self.pnl:+.2f} over {self.elapsed:.2f}d, "
                    f"{st.trades} trades. The bot has earned its keep.")
        if st.verdict == "failed":
            return (f"⛓️  PURGATORY — trial failed at net {self.pnl:+.2f}. "
                    f"Locked until a human releases it.")
        # still on trial
        passing = self.pnl >= cfg.min_pnl and st.trades >= cfg.min_trades
        mark = "PASSING" if passing else "FAILING"
        return (f"⏳ ON TRIAL — day {self.elapsed:.2f}/{cfg.trial_days:g} "
                f"({self.days_left:.2f}d left) · net {self.pnl:+.2f} "
                f"(need ≥{cfg.min_pnl:+.2f}) · {st.trades} trades "
                f"(need ≥{cfg.min_trades}) · verdict so far: {mark}")
