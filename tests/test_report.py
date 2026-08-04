"""Offline tests for the performance report summary logic."""

import report


def _t(inst, pl, close_epoch="1785000000"):
    return {"instrument": inst, "realizedPL": str(pl), "closeTime": close_epoch}


def test_summarize_counts_and_pl():
    trades = [_t("EUR_USD", 5.0), _t("EUR_USD", -2.0), _t("GBP_JPY", 3.0), _t("USD_JPY", 0.0)]
    s = report.summarize(trades)
    assert s["trades"] == 4
    assert s["wins"] == 2 and s["losses"] == 1 and s["flat"] == 1
    assert s["gross_profit"] == 8.0 and s["gross_loss"] == -2.0
    assert s["net"] == 6.0
    assert abs(s["win_rate"] - (2 / 3 * 100)) < 1e-6
    assert abs(s["profit_factor"] - 4.0) < 1e-6


def test_summarize_best_and_worst_and_per_instrument():
    trades = [_t("EUR_USD", 5.0), _t("GBP_JPY", -7.0), _t("EUR_USD", 2.0)]
    s = report.summarize(trades)
    assert s["best"] == ("EUR_USD", 5.0)
    assert s["worst"] == ("GBP_JPY", -7.0)
    assert s["per_instrument"]["EUR_USD"] == {"n": 2, "pl": 7.0}


def test_summarize_profit_factor_infinite_when_no_losses():
    s = report.summarize([_t("EUR_USD", 5.0), _t("EUR_USD", 1.0)])
    assert s["profit_factor"] == float("inf")


def test_summarize_since_filter_excludes_old_trades():
    trades = [_t("EUR_USD", 5.0, close_epoch="1000"),      # old
              _t("GBP_JPY", 3.0, close_epoch="2000000000")]  # recent
    s = report.summarize(trades, since_epoch=1_000_000_000)
    assert s["trades"] == 1
    assert s["net"] == 3.0
