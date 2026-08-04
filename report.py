#!/usr/bin/env python3
"""
Performance report for the OANDA bot — your "did it pass this week?" scorecard.

    python report.py            # summarise all closed trades on the account
    python report.py 7          # only trades closed in the last 7 days

Pulls closed trades straight from OANDA (the source of truth — realised P/L,
not the bot's own log) and prints win rate, net P/L, profit factor, best/worst,
and a per-instrument breakdown, plus the current open exposure. Use it at the
end of the demo week to decide whether the strategy earns its keep before you
ever point it at real money.
"""

from __future__ import annotations

import sys
import time
from collections import defaultdict

import oanda_trader as ot
from oanda_trader import Config, OandaClient, candle_epoch


def fetch_closed_trades(client: OandaClient, count: int = 500) -> list:
    data = client._request(
        "GET", f"/v3/accounts/{Config.ACCOUNT_ID}/trades",
        params={"state": "CLOSED", "count": count},
    )
    return (data or {}).get("trades", [])


def summarize(trades: list, since_epoch: float | None = None) -> dict:
    wins = losses = flat = 0
    gross_profit = gross_loss = 0.0
    per_inst = defaultdict(lambda: {"n": 0, "pl": 0.0})
    best = worst = None
    considered = 0

    for t in trades:
        if since_epoch is not None:
            ct = t.get("closeTime") or t.get("openTime")
            if ct and candle_epoch(ct) < since_epoch:
                continue
        pl = float(t.get("realizedPL", 0) or 0)
        inst = t.get("instrument", "?")
        considered += 1
        per_inst[inst]["n"] += 1
        per_inst[inst]["pl"] += pl
        if pl > 0:
            wins += 1
            gross_profit += pl
        elif pl < 0:
            losses += 1
            gross_loss += pl
        else:
            flat += 1
        if best is None or pl > best[1]:
            best = (inst, pl)
        if worst is None or pl < worst[1]:
            worst = (inst, pl)

    net = gross_profit + gross_loss
    decided = wins + losses
    win_rate = (wins / decided * 100) if decided else 0.0
    profit_factor = (gross_profit / abs(gross_loss)) if gross_loss else float("inf")
    return {
        "trades": considered, "wins": wins, "losses": losses, "flat": flat,
        "win_rate": win_rate, "gross_profit": gross_profit, "gross_loss": gross_loss,
        "net": net, "profit_factor": profit_factor, "best": best, "worst": worst,
        "per_instrument": dict(per_inst),
    }


def _pf(x):
    return "∞" if x == float("inf") else f"{x:.2f}"


def main():
    days = None
    if len(sys.argv) > 1:
        try:
            days = float(sys.argv[1])
        except ValueError:
            print(f"Usage: python report.py [days]   (got {sys.argv[1]!r})")
            raise SystemExit(1)
    since = (time.time() - days * 86400) if days else None

    client = OandaClient(ot._load_api_token())
    acct = client.get_account_details()
    if not acct:
        print("Could not reach OANDA (check token / account id).")
        raise SystemExit(1)

    s = summarize(fetch_closed_trades(client), since)

    window = f"last {days:g} days" if days else "all time"
    print("=" * 56)
    print(f" OANDA performance — {acct.get('id')} ({acct.get('currency')}) · {window}")
    print("=" * 56)
    print(f" Closed trades : {s['trades']}   (W {s['wins']} / L {s['losses']} / flat {s['flat']})")
    print(f" Win rate      : {s['win_rate']:.1f}%")
    print(f" Net P/L       : ${s['net']:,.2f}")
    print(f" Gross profit  : ${s['gross_profit']:,.2f}   Gross loss: ${s['gross_loss']:,.2f}")
    print(f" Profit factor : {_pf(s['profit_factor'])}")
    if s["best"]:
        print(f" Best / worst  : {s['best'][0]} ${s['best'][1]:,.2f}  /  {s['worst'][0]} ${s['worst'][1]:,.2f}")
    if s["per_instrument"]:
        print("-" * 56)
        print(" Per instrument:")
        for inst, d in sorted(s["per_instrument"].items(), key=lambda kv: kv[1]["pl"], reverse=True):
            print(f"   {inst:<10} {d['n']:>3} trades   ${d['pl']:>10,.2f}")
    print("-" * 56)
    print(f" Balance ${float(acct.get('balance',0)):,.2f} | NAV ${float(acct.get('NAV',0)):,.2f} "
          f"| open trades {acct.get('openTradeCount')} | unrealized ${float(acct.get('unrealizedPL',0)):,.2f}")
    print("=" * 56)


if __name__ == "__main__":
    main()
