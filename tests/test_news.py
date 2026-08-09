"""Tests for the news intelligence layer (pure logic; no network)."""

import time

import news
import oanda_trader as ot


def test_classify_high_impact_geopolitics():
    c = news.classify("Russia launches missile attack on Ukraine, markets tumble")
    assert c["impact"] == "high"
    assert c["posture"] == "risk_off"


def test_classify_macro_policy_currency():
    c = news.classify("Federal Reserve signals surprise interest rate hike")
    assert c["impact"] == "high"
    assert "USD" in c["currencies"]


def test_classify_risk_on():
    c = news.classify("Global stocks rally as ceasefire deal boosts optimism")
    assert c["posture"] == "risk_on"


def test_classify_low_impact_neutral():
    c = news.classify("Local museum unveils new sculpture exhibit")
    assert c["impact"] == "low"
    assert c["posture"] == "neutral"
    assert c["currencies"] == []


def test_currency_mapping_multi():
    c = news.classify("ECB and Bank of England diverge as euro and pound swing")
    assert "EUR" in c["currencies"] and "GBP" in c["currencies"]


def test_parse_rss_extracts_and_classifies():
    xml = """<?xml version="1.0"?><rss><channel>
      <item><title>Federal Reserve delivers interest rate hike, dollar surges</title>
        <link>http://x/1</link><pubDate>Mon, 04 Aug 2026 12:00:00 +0000</pubDate></item>
      <item><title>Cat rescued from tree</title><link>http://x/2</link></item>
    </channel></rss>"""
    heads = news.parse_rss(xml, "Test")
    assert len(heads) == 2
    assert heads[0].impact == "high" and "USD" in heads[0].currencies
    assert heads[0].ts > 0            # pubDate parsed to epoch


def test_aggregate_posture_levels():
    now = time.time()
    def h(title, ts=None):
        c = news.classify(title)
        return news.Headline("S", title, "", "", ts if ts is not None else now,
                             c["impact"], c["posture"], c["currencies"])
    calm = news.aggregate_posture([h("museum opens"), h("recipe of the day")])
    assert calm["level"] == "calm"
    hot = news.aggregate_posture([
        h("war escalates as missile attack hits city"),
        h("market crash deepens amid recession fears"),
        h("central bank emergency rate cut announced"),
    ])
    assert hot["level"] == "high"
    assert hot["posture"] == "risk_off"


def test_aggregate_ignores_stale_by_time():
    old = time.time() - 48 * 3600
    h = news.Headline("S", "war missile attack crisis", "", "", old, "high", "risk_off", ["USD"])
    agg = news.aggregate_posture([h], within_hours=6)
    assert agg["high_impact"] == 0    # too old to count


def test_news_veto_blocks_matching_pair(tmp_path, monkeypatch):
    import json
    now = time.time()
    feed = {"headlines": [
        {"title": "Fed shock hike", "impact": "high", "ts": now - 300, "currencies": ["USD"]},
    ]}
    d = tmp_path / "logs"; d.mkdir()
    (d / "news_feed.json").write_text(json.dumps(feed))
    monkeypatch.setattr(ot.Config, "LOG_DIR", d)
    monkeypatch.setattr(ot.Config, "NEWS_VETO_MINUTES", 30)
    assert ot.news_veto("EUR_USD", now=now)      # USD in pair -> vetoed
    assert ot.news_veto("AUD_CAD", now=now) is None  # no shared currency


def test_news_veto_expired_event_does_not_block(tmp_path, monkeypatch):
    import json
    now = time.time()
    feed = {"headlines": [
        {"title": "old fed news", "impact": "high", "ts": now - 3 * 3600, "currencies": ["USD"]},
    ]}
    d = tmp_path / "logs"; d.mkdir()
    (d / "news_feed.json").write_text(json.dumps(feed))
    monkeypatch.setattr(ot.Config, "LOG_DIR", d)
    monkeypatch.setattr(ot.Config, "NEWS_VETO_MINUTES", 30)
    assert ot.news_veto("EUR_USD", now=now) is None


def test_news_veto_no_feed_never_blocks(tmp_path, monkeypatch):
    monkeypatch.setattr(ot.Config, "LOG_DIR", tmp_path)
    assert ot.news_veto("EUR_USD") is None
