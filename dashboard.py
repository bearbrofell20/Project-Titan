#!/usr/bin/env python3
"""
Live web dashboard for the OANDA momentum bot (Project Titan).

Run it alongside (or instead of) the bot:

    python dashboard.py                 # then open http://localhost:8080

It queries your OANDA practice account live, computes the current RSI / trend /
signal for every monitored pair (reusing the bot's own logic), and reads the
bot's trade log. A background thread refreshes the data every few seconds; the
browser just polls a local JSON endpoint, so the page stays snappy regardless of
API latency. Your API token never leaves this process — the browser only ever
talks to localhost.

Environment: same variables as the bot (OANDA_API_TOKEN / oanda_config.py, etc.).
Extra knobs: DASHBOARD_PORT (default 8080), DASHBOARD_REFRESH secs (default 8).
"""

from __future__ import annotations

import glob
import json
import os
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import oanda_trader as ot
from oanda_trader import Config, MomentumDetector, OandaClient, completed_candles

PORT = int(os.getenv("DASHBOARD_PORT", "8080"))
REFRESH = int(os.getenv("DASHBOARD_REFRESH", "8"))

# Shared snapshot updated by the background thread, served by the HTTP handler.
_STATE: dict = {"status": "starting", "time": None}
_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# Data gathering (pure-ish: takes a client so it can be tested offline)
# ---------------------------------------------------------------------------


def _f(x, default=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def build_account_snapshot(client: OandaClient) -> dict:
    a = client.get_account_details()
    if not a:
        return {}
    return {
        "id": a.get("id"),
        "currency": a.get("currency"),
        "balance": _f(a.get("balance")),
        "nav": _f(a.get("NAV")),
        "unrealizedPL": _f(a.get("unrealizedPL")),
        "realizedPL": _f(a.get("pl")),
        "marginUsed": _f(a.get("marginUsed")),
        "marginCloseoutPercent": _f(a.get("marginCloseoutPercent")) * 100,
        "openTradeCount": a.get("openTradeCount", 0),
    }


def build_positions(client: OandaClient) -> list:
    data = client._request("GET", f"/v3/accounts/{Config.ACCOUNT_ID}/openPositions")
    out = []
    for p in (data or {}).get("positions", []):
        long_u = int(_f(p.get("long", {}).get("units")))
        short_u = int(_f(p.get("short", {}).get("units")))
        side = p.get("long") if long_u else p.get("short")
        units = long_u or short_u
        out.append(
            {
                "instrument": p["instrument"],
                "units": units,
                "avgPrice": _f(side.get("averagePrice")) if side else 0.0,
                "unrealizedPL": _f(p.get("unrealizedPL")),
            }
        )
    return out


def build_market_snapshot(client: OandaClient) -> list:
    rows = []
    for inst in Config.INSTRUMENTS:
        raw = client.get_candles(inst, granularity=Config.TIMEFRAME, count=Config.CANDLE_COUNT)
        candles = completed_candles(raw)
        row = {"instrument": inst, "price": None, "rsi": None, "trend": None, "signal": None}
        if len(candles) >= 20:
            closes = [_f(c["mid"]["c"]) for c in candles]
            row["price"] = closes[-1]
            rsi = MomentumDetector.calculate_rsi(closes, Config.RSI_PERIOD)
            row["rsi"] = round(rsi, 1) if rsi is not None else None
            row["trend"] = MomentumDetector.detect_trend(candles, Config.TREND_PERIOD)
            row["signal"] = MomentumDetector.get_signal(candles, inst)
        rows.append(row)
    return rows


def read_recent_trades(limit: int = 15) -> list:
    files = sorted(glob.glob(str(Config.LOG_DIR / "trades_*.json")))
    if not files:
        return []
    try:
        with open(files[-1]) as fh:
            trades = json.load(fh)
        return trades[-limit:][::-1]
    except Exception:
        return []


def bot_running() -> bool:
    """Heuristic: a bot log touched within ~2 poll intervals means it's live."""
    logs = glob.glob(str(Config.LOG_DIR / "bot_*.log"))
    if not logs:
        return False
    newest = max(os.path.getmtime(p) for p in logs)
    return (time.time() - newest) < max(2 * Config.POLL_INTERVAL, 90)


def build_state(client: OandaClient) -> dict:
    account = build_account_snapshot(client)
    if not account:
        return {"status": "error",
                "error": "Could not reach OANDA (check token / account id).",
                "time": datetime.now(timezone.utc).isoformat()}
    return {
        "status": "ok",
        "time": datetime.now(timezone.utc).isoformat(),
        "config": {
            "env": "LIVE" if Config.is_live_endpoint() else "DEMO",
            "risk": Config.RISK_PER_TRADE,
            "sl": Config.STOP_LOSS_PIPS,
            "tp": Config.TAKE_PROFIT_PIPS,
            "rsi_os": Config.RSI_OVERSOLD,
            "rsi_ob": Config.RSI_OVERBOUGHT,
            "pairs": len(Config.INSTRUMENTS),
        },
        "bot_running": bot_running(),
        "account": account,
        "positions": build_positions(client),
        "market": build_market_snapshot(client),
        "trades": read_recent_trades(),
    }


# ---------------------------------------------------------------------------
# Background refresher
# ---------------------------------------------------------------------------


def refresher():
    token = ot._load_api_token()
    if not token:
        with _LOCK:
            _STATE.clear()
            _STATE.update({"status": "error", "error": "No API token configured."})
        return
    client = OandaClient(token)
    while True:
        try:
            state = build_state(client)
        except Exception as e:  # never let the refresher die
            state = {"status": "error", "error": str(e),
                     "time": datetime.now(timezone.utc).isoformat()}
        with _LOCK:
            _STATE.clear()
            _STATE.update(state)
        time.sleep(REFRESH)


# ---------------------------------------------------------------------------
# HTTP server
# ---------------------------------------------------------------------------

INDEX_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Project Titan — OANDA Dashboard</title>
<style>
  :root{--bg:#0d1117;--card:#161b22;--line:#222c3a;--fg:#e6edf3;--mut:#8b949e;
        --green:#2ea043;--red:#f85149;--amber:#d29922;--blue:#388bfd;}
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--fg);
       font:14px/1.5 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif}
  header{display:flex;align-items:center;gap:14px;padding:16px 22px;border-bottom:1px solid var(--line)}
  header h1{font-size:16px;margin:0;font-weight:650;letter-spacing:.2px}
  .pill{font-size:11px;padding:2px 9px;border-radius:999px;border:1px solid var(--line);color:var(--mut)}
  .pill.on{color:var(--green);border-color:var(--green)}
  .pill.off{color:var(--mut)}
  .pill.demo{color:var(--blue);border-color:var(--blue)}
  .wrap{padding:20px 22px;max-width:1100px;margin:0 auto}
  .cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin-bottom:20px}
  .card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
  .card .k{font-size:11px;text-transform:uppercase;letter-spacing:.6px;color:var(--mut)}
  .card .v{font-size:22px;font-weight:650;margin-top:6px}
  h2{font-size:12px;text-transform:uppercase;letter-spacing:.7px;color:var(--mut);margin:22px 0 10px}
  table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden}
  th,td{text-align:right;padding:9px 12px;border-bottom:1px solid var(--line);font-variant-numeric:tabular-nums}
  th:first-child,td:first-child{text-align:left}
  th{font-size:11px;text-transform:uppercase;letter-spacing:.5px;color:var(--mut);font-weight:600}
  tr:last-child td{border-bottom:none}
  .pos{color:var(--green)} .neg{color:var(--red)} .mut{color:var(--mut)}
  .tag{font-size:11px;font-weight:700;padding:2px 8px;border-radius:6px}
  .tag.buy{background:rgba(46,160,67,.15);color:var(--green)}
  .tag.sell{background:rgba(248,81,73,.15);color:var(--red)}
  .tag.none{color:var(--mut)}
  .up{color:var(--green)} .down{color:var(--red)}
  .rsi-lo{color:var(--green);font-weight:650} .rsi-hi{color:var(--red);font-weight:650}
  .foot{color:var(--mut);font-size:12px;margin-top:18px}
  .err{background:rgba(248,81,73,.12);border:1px solid var(--red);color:#ffb4ae;padding:12px 16px;border-radius:10px;margin-bottom:16px}
  .dot{width:8px;height:8px;border-radius:50%;display:inline-block;margin-right:5px;vertical-align:middle}
  .dot.g{background:var(--green)} .dot.r{background:var(--red)}
</style></head>
<body>
<header>
  <h1>🤖 Project Titan · OANDA</h1>
  <span id="env" class="pill demo">—</span>
  <span id="botpill" class="pill off">bot: unknown</span>
  <span id="clock" class="pill">—</span>
</header>
<div class="wrap">
  <div id="err" class="err" style="display:none"></div>
  <div class="cards" id="cards"></div>
  <h2>Open positions</h2>
  <table id="positions"><thead><tr><th>Instrument</th><th>Units</th><th>Avg price</th><th>Unrealized P/L</th></tr></thead><tbody></tbody></table>
  <h2>Live signals</h2>
  <table id="market"><thead><tr><th>Pair</th><th>Price</th><th>RSI</th><th>Trend</th><th>Signal</th></tr></thead><tbody></tbody></table>
  <h2>Recent trades (bot log)</h2>
  <table id="trades"><thead><tr><th>Time</th><th>Instrument</th><th>Dir</th><th>Units</th><th>Entry</th><th>TP</th></tr></thead><tbody></tbody></table>
  <div class="foot" id="foot"></div>
</div>
<script>
const money=(n,d=2)=>(n<0?'-$':'$')+Math.abs(n).toLocaleString(undefined,{minimumFractionDigits:d,maximumFractionDigits:d});
const pnl=n=>`<span class="${n>0?'pos':n<0?'neg':'mut'}">${money(n)}</span>`;
function rsiCls(v){if(v==null)return'mut';if(v<30)return'rsi-lo';if(v>70)return'rsi-hi';return'';}
function trend(t){if(t==='UP')return'<span class="up">▲ up</span>';if(t==='DOWN')return'<span class="down">▼ down</span>';return'<span class="mut">— flat</span>';}
function sig(s){if(s==='BUY')return'<span class="tag buy">BUY</span>';if(s==='SELL')return'<span class="tag sell">SELL</span>';return'<span class="tag none">—</span>';}
async function tick(){
  let s; try{ s=await (await fetch('/api/state')).json(); }catch(e){ return; }
  const err=document.getElementById('err');
  if(s.status!=='ok'){ err.style.display='block'; err.textContent='⚠ '+(s.error||'not ready'); return; }
  err.style.display='none';
  const c=s.config, a=s.account;
  document.getElementById('env').textContent=c.env;
  document.getElementById('env').className='pill '+(c.env==='DEMO'?'demo':'on');
  const bp=document.getElementById('botpill');
  bp.innerHTML=`<span class="dot ${s.bot_running?'g':'r'}"></span>bot ${s.bot_running?'running':'stopped'}`;
  bp.className='pill '+(s.bot_running?'on':'off');
  document.getElementById('clock').textContent=new Date(s.time).toLocaleTimeString();
  document.getElementById('cards').innerHTML=[
    ['Balance',money(a.balance)],['NAV',money(a.nav)],
    ['Unrealized P/L',pnl(a.unrealizedPL)],['Realized P/L (lifetime)',pnl(a.realizedPL)],
    ['Open trades',a.openTradeCount],['Margin used',money(a.marginUsed)],
  ].map(([k,v])=>`<div class="card"><div class="k">${k}</div><div class="v">${v}</div></div>`).join('');
  const pos=s.positions.length? s.positions.map(p=>`<tr><td>${p.instrument}</td><td>${p.units}</td><td>${p.avgPrice||'—'}</td><td>${pnl(p.unrealizedPL)}</td></tr>`).join('')
                               :'<tr><td colspan="4" class="mut">No open positions</td></tr>';
  document.querySelector('#positions tbody').innerHTML=pos;
  document.querySelector('#market tbody').innerHTML=s.market.map(m=>
    `<tr><td>${m.instrument}</td><td>${m.price??'—'}</td>
     <td class="${rsiCls(m.rsi)}">${m.rsi??'—'}</td><td>${trend(m.trend)}</td><td>${sig(m.signal)}</td></tr>`).join('');
  const tr=s.trades.length? s.trades.map(t=>`<tr><td>${new Date(t.timestamp).toLocaleTimeString()}</td><td>${t.instrument}</td><td>${t.direction}</td><td>${t.units}</td><td>${(+t.entry_price).toFixed(5)}</td><td>${t.take_profit?(+t.take_profit).toFixed(5):'—'}</td></tr>`).join('')
                          :'<tr><td colspan="6" class="mut">No trades logged yet</td></tr>';
  document.querySelector('#trades tbody').innerHTML=tr;
  document.getElementById('foot').textContent=
    `Risk $${c.risk}/trade · SL ${c.sl} / TP ${c.tp} pips · RSI ${c.rsi_os}/${c.rsi_ob} · ${c.pairs} pairs · auto-refresh`;
}
tick(); setInterval(tick, 3000);
</script>
</body></html>"""


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/api/state"):
            with _LOCK:
                body = json.dumps(_STATE).encode()
            self._send(200, body, "application/json")
        elif self.path in ("/", "/index.html"):
            self._send(200, INDEX_HTML.encode(), "text/html; charset=utf-8")
        else:
            self._send(404, b"not found", "text/plain")

    def log_message(self, *args):  # silence per-request console noise
        pass


def main():
    threading.Thread(target=refresher, daemon=True).start()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"Dashboard on http://localhost:{PORT}  (refresh every {REFRESH}s, Ctrl-C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard stopped.")


if __name__ == "__main__":
    main()
