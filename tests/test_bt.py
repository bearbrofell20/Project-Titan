"""The realistic engine's fills, costs, and no-look-ahead must be correct — the
whole audit rests on trusting these numbers."""

import bt


def mba(bid, ask, t, hi=None, lo=None):
    """A flat-ish MBA candle at given bid/ask close; high/low default to close."""
    def side(px):
        h = hi if hi is not None else px
        l = lo if lo is not None else px
        return {"o": px, "h": h, "l": l, "c": px}
    mid = (bid + ask) / 2
    return {"time": t, "complete": True, "volume": 100,
            "bid": side(bid), "mid": side(mid), "ask": side(ask)}


def test_long_pays_spread_and_hits_target():
    pip = 0.0001
    # entry bar: bid 1.0000 / ask 1.0002 (2-pip spread); signal BUY
    candles = [mba(1.0000, 1.0002, i) for i in range(61)]
    candles.append(mba(1.0000, 1.0002, 61))                    # signal bar (i=61)
    # next bar reaches the target on the BID side
    candles.append(mba(1.0050, 1.0052, 62, hi=1.0100, lo=1.0050))
    signals = [None] * 61 + ["BUY", None]
    res = bt.simulate(candles, None, pip, exits=bt.ExitConfig(stop_pips=20, target_pips=40),
                      costs=bt.Costs(slippage_pips=0.0), warmup=60, signals=signals)
    tr = res["trades"]
    assert len(tr) == 1
    t = tr[0]
    # entered at the ask (1.0002), target 40 pips above = 1.0042, hit on bid high
    assert t.reason == "tp"
    assert abs(t.entry - 1.0002) < 1e-9
    assert abs(t.r_multiple - 2.0) < 1e-9   # 40-pip gain on a 20-pip risk = +2R


def test_long_stop_checked_before_target_when_bar_spans_both():
    pip = 0.0001
    candles = [mba(1.0000, 1.0002, i) for i in range(62)]
    signals = [None] * 61 + ["BUY"]
    # next bar's bid spans BOTH the stop and the target -> stop must win
    candles.append(mba(1.0000, 1.0002, 62, hi=1.0100, lo=0.9900))
    res = bt.simulate(candles, None, pip, exits=bt.ExitConfig(stop_pips=20, target_pips=40),
                      costs=bt.Costs(slippage_pips=0.0), warmup=60, signals=signals)
    t = res["trades"][0]
    assert t.reason == "sl"
    assert t.r_multiple < 0


def test_spread_gate_skips_trade():
    pip = 0.0001
    candles = [mba(1.0000, 1.0010, i) for i in range(62)]  # 10-pip spread
    signals = [None] * 61 + ["BUY"]
    res = bt.simulate(candles, None, pip, exits=bt.ExitConfig(stop_pips=20, target_pips=40),
                      warmup=60, signals=signals, gates=bt.Gates(max_spread_pips=3.0))
    assert res["trades"] == []
    assert res["skips"].get("spread") == 1


def test_session_gate_skips_outside_hours():
    pip = 0.0001
    # epoch 0 = 00:00 UTC; session gate only allows 12-16 -> skip
    candles = [mba(1.0000, 1.0002, i) for i in range(62)]
    signals = [None] * 61 + ["BUY"]
    res = bt.simulate(candles, None, pip, exits=bt.ExitConfig(stop_pips=20, target_pips=40),
                      warmup=60, signals=signals, gates=bt.Gates(sessions_utc=[(12, 16)]))
    assert res["skips"].get("session") == 1


def test_no_lookahead_entry_uses_signal_bar_close_then_walks_forward():
    # If the signal bar itself already shows the target, the trade must NOT close
    # on the signal bar — exit search starts on the NEXT bar.
    pip = 0.0001
    candles = [mba(1.0000, 1.0002, i) for i in range(61)]
    candles.append(mba(1.0000, 1.0002, 61, hi=1.0100))  # signal bar with a huge high
    candles.append(mba(1.0000, 1.0002, 62))             # flat next bar
    signals = [None] * 61 + ["BUY", None]
    res = bt.simulate(candles, None, pip, exits=bt.ExitConfig(stop_pips=20, target_pips=40),
                      warmup=60, signals=signals)
    # target not reachable on the flat next bar -> either still open (no trade) or
    # not a tp on the signal bar. Assert it did not book a tp from the signal bar.
    assert all(t.reason != "tp" for t in res["trades"])
