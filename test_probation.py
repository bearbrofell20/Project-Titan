"""Tests for the probation (testing-week) mechanism."""

from datetime import timedelta

import probation
from probation import Probation, ProbationConfig


def _cfg(tmp_path, **kw):
    kw.setdefault("trial_days", 7.0)
    kw.setdefault("min_trades", 5)
    kw.setdefault("min_pnl", 0.0)
    kw.setdefault("purgatory_file", str(tmp_path / "PURGATORY.txt"))
    return ProbationConfig(**kw)


def test_start_is_idempotent(tmp_path):
    p = Probation(_cfg(tmp_path), tmp_path)
    p.start(100.0)
    started = p.state.started_at
    p.start(999.0)  # should not reset baseline or clock
    assert p.state.baseline_nav == 100.0
    assert p.state.started_at == started


def test_state_persists_across_instances(tmp_path):
    cfg = _cfg(tmp_path)
    p = Probation(cfg, tmp_path)
    p.start(100.0)
    p.record(current_nav=105.0, trades=3)
    # a fresh instance reads the saved trial
    p2 = Probation(cfg, tmp_path)
    assert p2.state is not None
    assert p2.state.baseline_nav == 100.0
    assert p2.state.current_nav == 105.0


def test_on_trial_before_window_elapses(tmp_path):
    p = Probation(_cfg(tmp_path), tmp_path)
    start = probation._now()
    p.start(100.0)
    s = p.record(current_nav=90.0, trades=1, now=start + timedelta(days=1))
    assert s.verdict == "on_trial"
    assert not s.locked
    assert not p.is_locked()


def test_pass_graduates_no_lockout(tmp_path):
    p = Probation(_cfg(tmp_path), tmp_path)
    start = probation._now()
    p.start(100.0)
    s = p.record(current_nav=110.0, trades=6, now=start + timedelta(days=7, seconds=1))
    assert s.verdict == "passed"
    assert not s.locked
    assert not p.is_locked()
    assert "PASSED" in s.line


def test_fail_on_losing_pnl_writes_purgatory(tmp_path):
    cfg = _cfg(tmp_path)
    p = Probation(cfg, tmp_path)
    start = probation._now()
    p.start(100.0)
    s = p.record(current_nav=95.0, trades=6, now=start + timedelta(days=7, seconds=1))
    assert s.verdict == "failed"
    assert s.locked
    assert p.is_locked()
    body = p.purgatory_path.read_text()
    assert "PURGATORY" in body
    assert "-5.00" in body


def test_fail_when_not_enough_trades(tmp_path):
    # Profitable but idle: fewer than min_trades still fails.
    p = Probation(_cfg(tmp_path, min_trades=5), tmp_path)
    start = probation._now()
    p.start(100.0)
    s = p.record(current_nav=200.0, trades=2, now=start + timedelta(days=7, seconds=1))
    assert s.verdict == "failed"
    assert p.is_locked()


def test_enforce_lockout_blocks_when_condemned(tmp_path):
    cfg = _cfg(tmp_path)
    p = Probation(cfg, tmp_path)
    start = probation._now()
    p.start(100.0)
    p.record(current_nav=90.0, trades=6, now=start + timedelta(days=8))
    # a brand-new run sees the lockout
    p2 = Probation(cfg, tmp_path)
    notice = p2.enforce_lockout()
    assert notice is not None
    assert "not trade again" in notice


def test_release_by_deleting_file(tmp_path):
    cfg = _cfg(tmp_path)
    p = Probation(cfg, tmp_path)
    start = probation._now()
    p.start(100.0)
    p.record(current_nav=90.0, trades=6, now=start + timedelta(days=8))
    assert p.is_locked()
    p.purgatory_path.unlink()  # human releases it
    assert not p.is_locked()
    assert p.enforce_lockout() is None


def test_min_pnl_threshold(tmp_path):
    # Requiring a positive return: break-even is not enough.
    p = Probation(_cfg(tmp_path, min_pnl=50.0), tmp_path)
    start = probation._now()
    p.start(100.0)
    s = p.record(current_nav=140.0, trades=9, now=start + timedelta(days=7, seconds=1))
    assert s.verdict == "failed"  # +40 < required +50


def test_env_config(monkeypatch):
    monkeypatch.setenv("OANDA_TRIAL_DAYS", "3")
    monkeypatch.setenv("OANDA_TRIAL_MIN_TRADES", "10")
    monkeypatch.setenv("OANDA_TRIAL_MIN_PNL", "25.5")
    cfg = ProbationConfig.from_env()
    assert cfg.trial_days == 3.0
    assert cfg.min_trades == 10
    assert cfg.min_pnl == 25.5


def test_standing_line_reports_failing_while_on_trial(tmp_path):
    p = Probation(_cfg(tmp_path), tmp_path)
    start = probation._now()
    p.start(100.0)
    s = p.record(current_nav=80.0, trades=1, now=start + timedelta(days=2))
    assert "ON TRIAL" in s.line
    assert "FAILING" in s.line
