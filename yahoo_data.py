"""Fetch hourly FX history from Yahoo Finance into the OANDA-format cache.

Our OANDA practice token can only pull data from the machine it's bound to, so
for offline research on longer histories we use Yahoo's public chart endpoint.
Yahoo gives **mid** OHLC only, so we synthesize a symmetric bid/ask around it
using a constant half-spread (a *conservative* stand-in — real spreads widen at
news/rollover, so a positive backtest here still needs live-spread confirmation).

    python yahoo_data.py AUD_JPY EUR_JPY        # writes market_data/<pair>_H1.json

The cache format matches data.py exactly (list of candles with bid/mid/ask
o/h/l/c), so validate.py / bt.py consume it unchanged with gran="H1".
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

# pair -> (Yahoo symbol, half-spread in *price*). JPY crosses ~2-pip spread
# (0.01 pip size -> half 0.01), majors ~1.2-pip (0.0001 pip size -> half 0.00006).
SYMBOLS = {
    "AUD_JPY": ("AUDJPY=X", 0.010), "EUR_JPY": ("EURJPY=X", 0.010),
    "GBP_JPY": ("GBPJPY=X", 0.010), "USD_JPY": ("USDJPY=X", 0.010),
    "CAD_JPY": ("CADJPY=X", 0.010), "NZD_JPY": ("NZDJPY=X", 0.010),
    "CHF_JPY": ("CHFJPY=X", 0.010),
    "EUR_USD": ("EURUSD=X", 0.00006), "AUD_USD": ("AUDUSD=X", 0.00006),
    "GBP_USD": ("GBPUSD=X", 0.00006), "USD_CAD": ("USDCAD=X", 0.00006),
    "XAU_USD": ("GC=F", 0.15),  # gold: ~0.30 spread (OANDA-typical)
    # non-JPY trending crosses (quote pip 0.0001, ~3-pip synthetic spread)
    "GBP_AUD": ("GBPAUD=X", 0.00015), "EUR_AUD": ("EURAUD=X", 0.00015),
    "AUD_NZD": ("AUDNZD=X", 0.00015), "GBP_CAD": ("GBPCAD=X", 0.00015),
    "EUR_CAD": ("EURCAD=X", 0.00015), "AUD_CAD": ("AUDCAD=X", 0.00015),
    "GBP_NZD": ("GBPNZD=X", 0.00020), "EUR_NZD": ("EURNZD=X", 0.00020),
    # trending non-FX markets (test breakout the way gold passed)
    "SPX500_USD": ("ES=F", 0.25), "NAS100_USD": ("NQ=F", 0.75),
    "US30_USD": ("YM=F", 1.5), "WTICO_USD": ("CL=F", 0.02),
    "XAG_USD": ("SI=F", 0.015),
}
HDR = {"User-Agent": "Mozilla/5.0"}


def fetch(pair: str, interval: str = "1h", rng: str = "730d") -> int:
    sym, half = SYMBOLS[pair]
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
           f"?interval={interval}&range={rng}")
    req = urllib.request.Request(url, headers=HDR)
    d = json.load(urllib.request.urlopen(req, timeout=60))
    res = d["chart"]["result"][0]
    ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    o, h, l, c = q["open"], q["high"], q["low"], q["close"]
    out = []
    for i, t in enumerate(ts):
        if None in (o[i], h[i], l[i], c[i]):
            continue
        mid = {"o": o[i], "h": h[i], "l": l[i], "c": c[i]}
        out.append({
            "time": int(t), "complete": True, "volume": 0,
            "bid": {k: v - half for k, v in mid.items()},
            "mid": mid,
            "ask": {k: v + half for k, v in mid.items()},
        })
    gran = "H1" if interval == "1h" else interval.upper()
    path = Path("market_data") / f"{pair}_{gran}.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(out))
    return len(out)


def main(argv):
    pairs = argv or ["AUD_JPY", "EUR_JPY"]
    for p in pairs:
        if p not in SYMBOLS:
            print(f"skip {p}: no Yahoo symbol mapped")
            continue
        n = fetch(p)
        print(f"{p}: {n} bars -> market_data/{p}_H1.json")
        time.sleep(1)


if __name__ == "__main__":
    main(sys.argv[1:])
