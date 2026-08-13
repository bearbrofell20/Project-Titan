"""Tests for the event->reaction collector's pure logic."""
import json
import event_study as es


def test_move_pips_signs():
    assert es.move_pips("EUR_USD", 1.1000, 1.1010) == 10.0
    assert es.move_pips("USD_JPY", 150.00, 150.30) == 30.0
    assert es.move_pips("EUR_USD", 1.1000, 1.0995) == -5.0


def test_analyze_describes_distribution(tmp_path):
    p = tmp_path / "ev.jsonl"
    rows = [
        {"posture":"risk_off","moves":{"30":-8.0}},
        {"posture":"risk_off","moves":{"30":-4.0}},
        {"posture":"risk_on","moves":{"30":6.0}},
    ]
    p.write_text("\n".join(json.dumps(r) for r in rows))
    out = es.analyze(str(p), horizon="30")
    assert out["usable"] == 3
    assert out["avg_abs_move_pips"] == 6.0          # (8+4+6)/3
    assert out["risk_off_mean_pips"] == -6.0        # (-8-4)/2
    assert out["risk_on_n"] == 1


def test_analyze_empty():
    assert es.analyze("does_not_exist.jsonl")["events"] == 0


def test_ccy_pair_coverage():
    for c in ("USD","EUR","GBP","JPY","CHF","CAD","AUD"):
        assert c in es.CCY_PAIR
