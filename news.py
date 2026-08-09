"""World-affairs intelligence layer for Project Titan.

Scans free news RSS feeds, classifies each headline for **market impact**,
**risk posture** (risk-on / risk-off), and **which currencies it touches**, then
writes a compact ``news_feed.json`` the dashboard displays and the trade bot can
consult as an *event-risk filter*.

Honest scope: this does not predict prices. Its defensible job is situational
awareness — surfacing what's happening and letting the trader **stand aside**
around high-impact events (news spikes cause slippage and gaps). Using news to
*generate* entries is unproven and deliberately not attempted here.

Pure functions (parse/classify/aggregate) are unit-tested; the fetcher hits
public RSS endpoints and is exercised live.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional
from xml.etree import ElementTree as ET

FEEDS = [
    ("BBC World", "https://feeds.bbci.co.uk/news/world/rss.xml"),
    ("BBC Business", "https://feeds.bbci.co.uk/news/business/rss.xml"),
    ("Yahoo Finance", "https://finance.yahoo.com/news/rssindex"),
    ("CNBC", "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114"),
]

# --- keyword lexicons ------------------------------------------------------
# High-impact, market-moving themes (geopolitics + macro policy + shocks).
HIGH_IMPACT = [
    "war", "invasion", "invade", "airstrike", "missile", "attack", "conflict",
    "sanction", "tariff", "embargo", "opec", "oil price", "nuclear", "coup",
    "central bank", "federal reserve", "the fed", "rate hike", "rate cut",
    "interest rate", "inflation", "cpi", "ppi", "jobs report", "nonfarm",
    "payrolls", "recession", "default", "downgrade", "crisis", "crash",
    "collapse", "emergency", "shutdown", "election", "stimulus", "gdp",
    "ecb", "boe", "boj", "pboc", "unemployment",
]
RISK_OFF = [
    "war", "invasion", "attack", "conflict", "crisis", "crash", "collapse",
    "plunge", "plummet", "selloff", "sell-off", "fear", "recession", "default",
    "downgrade", "slump", "tumble", "sanction", "escalate", "warns", "threat",
    "shutdown", "layoff", "layoffs", "contraction",
]
RISK_ON = [
    "rally", "surge", "soar", "record high", "rebound", "optimism", "deal",
    "agreement", "ceasefire", "recovery", "growth", "beats", "upgrade",
    "stimulus", "boom", "gains", "jumps",
]
# Currency exposure by keyword.
CURRENCY_KEYS = {
    "USD": ["fed", "federal reserve", "u.s.", "us ", "united states", "dollar", "america", "washington"],
    "EUR": ["ecb", "euro", "eurozone", "germany", "france", "european"],
    "GBP": ["boe", "bank of england", "uk ", "u.k.", "britain", "british", "pound", "sterling"],
    "JPY": ["boj", "bank of japan", "japan", "yen", "tokyo"],
    "CHF": ["swiss", "switzerland", "franc"],
    "CAD": ["canada", "canadian", "oil", "crude", "opec"],
    "AUD": ["australia", "australian", "rba"],
    "CNH": ["china", "chinese", "yuan", "beijing", "pboc"],
}


@dataclass
class Headline:
    source: str
    title: str
    link: str
    published: str          # ISO if parseable, else raw
    ts: float               # epoch seconds (best-effort)
    impact: str = "low"     # high | medium | low
    posture: str = "neutral"  # risk_off | risk_on | neutral
    currencies: List[str] = field(default_factory=list)


def _has(text: str, words) -> bool:
    return any(w in text for w in words)


def classify(title: str) -> Dict[str, object]:
    """Impact, risk posture, and affected currencies for one headline."""
    t = " " + title.lower() + " "
    impact = "high" if _has(t, HIGH_IMPACT) else "low"
    off = sum(t.count(w) for w in RISK_OFF)
    on = sum(t.count(w) for w in RISK_ON)
    posture = "risk_off" if off > on else ("risk_on" if on > off else "neutral")
    if impact == "low" and posture != "neutral":
        impact = "medium"
    currencies = [c for c, keys in CURRENCY_KEYS.items() if _has(t, keys)]
    return {"impact": impact, "posture": posture, "currencies": currencies}


def _parse_pubdate(s: str) -> float:
    """Best-effort RSS pubDate -> epoch seconds; 0.0 if unknown."""
    if not s:
        return 0.0
    for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z",
                "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return datetime.strptime(s.strip(), fmt).timestamp()
        except ValueError:
            continue
    return 0.0


def parse_rss(xml_text: str, source: str) -> List[Headline]:
    """Parse an RSS 2.0 document into classified Headlines."""
    out: List[Headline] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return out
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        if not title:
            continue
        link = (item.findtext("link") or "").strip()
        pub = (item.findtext("pubDate") or "").strip()
        ts = _parse_pubdate(pub)
        c = classify(title)
        out.append(Headline(
            source=source, title=title, link=link,
            published=(datetime.fromtimestamp(ts, timezone.utc).isoformat() if ts else pub),
            ts=ts, impact=c["impact"], posture=c["posture"], currencies=c["currencies"],
        ))
    return out


def aggregate_posture(headlines: List[Headline], within_hours: float = 6.0) -> Dict[str, object]:
    """Overall market-risk posture from recent high/medium-impact headlines.

    Returns a level (calm | elevated | high) plus counts and per-currency tallies,
    driven by how many impactful risk-off vs risk-on stories are recent.
    """
    now = time.time()
    recent = [h for h in headlines if h.ts == 0 or (now - h.ts) <= within_hours * 3600]
    impactful = [h for h in recent if h.impact in ("high", "medium")]
    off = sum(1 for h in impactful if h.posture == "risk_off")
    on = sum(1 for h in impactful if h.posture == "risk_on")
    high = sum(1 for h in recent if h.impact == "high")
    if high >= 3 or off >= 4:
        level = "high"
    elif high >= 1 or off >= 2:
        level = "elevated"
    else:
        level = "calm"
    posture = "risk_off" if off > on else ("risk_on" if on > off else "neutral")
    ccy: Dict[str, int] = {}
    for h in impactful:
        for c in h.currencies:
            ccy[c] = ccy.get(c, 0) + 1
    return {"level": level, "posture": posture, "risk_off": off, "risk_on": on,
            "high_impact": high, "currencies": ccy}


class NewsScanner:
    def __init__(self, feeds=FEEDS, keep: int = 40, timeout: int = 12):
        self.feeds = feeds
        self.keep = keep
        self.timeout = timeout

    def fetch(self) -> List[Headline]:
        import requests
        seen, out = set(), []
        for source, url in self.feeds:
            try:
                r = requests.get(url, timeout=self.timeout,
                                 headers={"User-Agent": "Mozilla/5.0 TitanNews/1.0"})
                if r.status_code != 200:
                    continue
                for h in parse_rss(r.text, source):
                    key = h.title.lower()
                    if key in seen:
                        continue
                    seen.add(key)
                    out.append(h)
            except Exception:
                continue
        out.sort(key=lambda h: h.ts, reverse=True)
        return out

    def scan(self) -> Dict[str, object]:
        heads = self.fetch()
        agg = aggregate_posture(heads)
        top = heads[: self.keep]
        counts: Dict[str, int] = {}
        for h in heads:
            counts[h.source] = counts.get(h.source, 0) + 1
        sources = [{"name": name, "url": url, "count": counts.get(name, 0)}
                   for name, url in self.feeds]
        return {
            "updated": datetime.now(timezone.utc).isoformat(),
            "count": len(heads),
            "risk": agg,
            "sources": sources,
            "headlines": [asdict(h) for h in top],
        }


def write_feed(state: Dict[str, object], path) -> None:
    from pathlib import Path
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=2))


def load_feed(path) -> Optional[Dict[str, object]]:
    from pathlib import Path
    p = Path(path)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None
