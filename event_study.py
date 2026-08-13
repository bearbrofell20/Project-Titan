"""Event → reaction collector — the forex news-edge experiment.

The open question: when a HIGH-impact headline (or a Trump post) hits a currency,
does its pair move in a catchable, repeatable way afterward? Price history can't
answer that (we don't have timestamped news history), so we collect it **forward**:

For each new high-impact event touching a currency, snapshot the affected major
pair's price at t0, then again at +5/+15/+30/+60 minutes. Each completed record
is appended to ``event_reactions.jsonl``. After enough events accumulate,
``analyze()`` measures whether a real, tradeable reaction exists — same honest
bar as everything else (out-of-sample, net of cost).

Runs as a thread in run_all.py (needs the OANDA client for live prices).
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Dict, List, Optional

# Which major pair best isolates each currency, and whether the currency is the
# base (+1) or quote (-1) of that pair — so a currency's *strength* maps to a
# known sign of the pair's move.
CCY_PAIR = {
    "USD": ("EUR_USD", -1), "EUR": ("EUR_USD", +1), "GBP": ("GBP_USD", +1),
    "JPY": ("USD_JPY", -1), "CHF": ("USD_CHF", -1), "CAD": ("USD_CAD", -1),
    "AUD": ("AUD_USD", +1),
}
HORIZONS_MIN = [5, 15, 30, 60]


def pip_size(pair: str) -> float:
    return 0.01 if pair.endswith("JPY") else 0.0001


def move_pips(pair: str, p0: float, p1: float) -> float:
    return round((p1 - p0) / pip_size(pair), 2)


class EventCollector:
    def __init__(self, log_dir="trade_logs"):
        self.dir = Path(log_dir)
        self.pending_path = self.dir / "event_pending.json"
        self.out_path = self.dir / "event_reactions.jsonl"
        self.seen_path = self.dir / "event_seen.json"
        self.pending: List[dict] = self._load(self.pending_path, [])
        self.seen: set = set(self._load(self.seen_path, []))

    def _load(self, path, default):
        try:
            return json.loads(path.read_text())
        except Exception:
            return default

    def _save(self):
        self.dir.mkdir(parents=True, exist_ok=True)
        self.pending_path.write_text(json.dumps(self.pending))
        self.seen_path.write_text(json.dumps(list(self.seen)[-500:]))

    def _price(self, client, pair) -> Optional[float]:
        try:
            candles = client.get_candles(pair, granularity="M1", count=1)
            c = [x for x in candles]
            return float(c[-1]["mid"]["c"]) if c else None
        except Exception:
            return None

    def poll(self, client, now: Optional[float] = None):
        """One tick: register new high-impact events, fill elapsed horizons."""
        now = now if now is not None else time.time()
        feed = self._load(self.dir / "news_feed.json", None)
        # 1) register new high-impact events
        for h in (feed or {}).get("headlines", []):
            if h.get("impact") != "high":
                continue
            key = (h.get("title") or "")[:80]
            if not key or key in self.seen:
                continue
            for ccy in h.get("currencies", []):
                if ccy not in CCY_PAIR:
                    continue
                pair, sign = CCY_PAIR[ccy]
                p0 = self._price(client, pair)
                if p0 is None:
                    continue
                self.pending.append({
                    "event_ts": now, "title": key, "currency": ccy, "sign": sign,
                    "posture": h.get("posture"), "leader": bool(h.get("leader")),
                    "pair": pair, "p0": p0, "moves": {},
                })
            self.seen.add(key)
        # 2) fill elapsed horizons; complete finished events
        still = []
        for ev in self.pending:
            age_min = (now - ev["event_ts"]) / 60.0
            for hz in HORIZONS_MIN:
                if age_min >= hz and str(hz) not in ev["moves"]:
                    px = self._price(client, ev["pair"])
                    if px is not None:
                        ev["moves"][str(hz)] = round(move_pips(ev["pair"], ev["p0"], px), 1)
            if len(ev["moves"]) >= len(HORIZONS_MIN) or age_min > 120:
                with open(self.out_path, "a") as fh:
                    fh.write(json.dumps(ev) + "\n")
            else:
                still.append(ev)
        self.pending = still
        self._save()
        return len(self.pending)


def analyze(path="trade_logs/event_reactions.jsonl", horizon="30") -> Dict[str, object]:
    """Describe the reaction distribution — no baked thesis. Two honest questions:
    (1) does high-impact news move the pair at all (avg |move|)? that's the value
    of the event-risk *veto*; (2) is there any directional tendency, split by
    risk-off vs risk-on posture? Needs a real sample to mean anything."""
    rows = []
    try:
        with open(path) as fh:
            rows = [json.loads(l) for l in fh if l.strip()]
    except FileNotFoundError:
        return {"events": 0}
    moves = [(r.get("posture"), r["moves"][horizon])
             for r in rows if r.get("moves", {}).get(horizon) is not None]
    n = len(moves)
    if n == 0:
        return {"events": len(rows), "usable": 0}
    def mean(xs):
        return round(sum(xs) / len(xs), 2) if xs else None
    off = [m for p, m in moves if p == "risk_off"]
    on = [m for p, m in moves if p == "risk_on"]
    return {
        "events": len(rows), "usable": n, "horizon_min": horizon,
        "avg_abs_move_pips": mean([abs(m) for _, m in moves]),  # volatility -> veto value
        "risk_off_mean_pips": mean(off), "risk_off_n": len(off),
        "risk_on_mean_pips": mean(on), "risk_on_n": len(on),
        "note": "avg_abs_move >> spread ~> news moves price (veto useful); a stable "
                "directional mean by posture ~> a possible entry edge (needs many events)",
    }
