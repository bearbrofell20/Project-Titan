#!/usr/bin/env python3
"""
Unified live dashboard for Project Titan — watches BOTH trading bots at once:

  * OANDA  (forex)            — account, live per-pair signals, positions, trades
  * Kalshi (event contracts)  — account balance and open positions

    python dashboard.py                 # then open http://localhost:8080

Each venue is independent: if a venue's credentials aren't configured it simply
shows "not configured" instead of erroring, so you can run OANDA-only, Kalshi-
only, or both. A background thread refreshes the data; the browser polls a local
JSON endpoint. Tokens never leave this process — the browser only talks to
localhost.

Env: OANDA_* (see oanda_trader) and KALSHI_* (see kalshi_trader). Extra knobs:
DASHBOARD_PORT (default 8080), DASHBOARD_REFRESH secs (default 8).
"""

from __future__ import annotations

import glob
import json
import os
import shlex
import subprocess
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import oanda_trader as ot
from oanda_trader import (Config, MarketAnalyzer, MomentumDetector, OandaClient,
                          adx, completed_candles, signal_for)

PORT = int(os.getenv("DASHBOARD_PORT", "8080"))
REFRESH = int(os.getenv("DASHBOARD_REFRESH", "8"))

_STATE: dict = {"status": "starting", "time": None}
_LOCK = threading.Lock()


def _f(x, default=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# OANDA venue
# ---------------------------------------------------------------------------


def _oanda_account(client):
    a = client.get_account_details()
    if not a:
        return None
    return {
        "id": a.get("id"), "currency": a.get("currency"),
        "balance": _f(a.get("balance")), "nav": _f(a.get("NAV")),
        "unrealizedPL": _f(a.get("unrealizedPL")), "realizedPL": _f(a.get("pl")),
        "marginUsed": _f(a.get("marginUsed")), "openTradeCount": a.get("openTradeCount", 0),
    }


def _oanda_positions(client):
    data = client._request("GET", f"/v3/accounts/{Config.ACCOUNT_ID}/openPositions")
    out = []
    for p in (data or {}).get("positions", []):
        long_u = int(_f(p.get("long", {}).get("units")))
        short_u = int(_f(p.get("short", {}).get("units")))
        side = p.get("long") if long_u else p.get("short")
        out.append({
            "instrument": p["instrument"], "units": long_u or short_u,
            "avgPrice": _f(side.get("averagePrice")) if side else 0.0,
            "unrealizedPL": _f(p.get("unrealizedPL")),
        })
    return out


def _oanda_market(client):
    rows = []
    for inst in Config.INSTRUMENTS:
        raw = client.get_candles(inst, granularity=Config.TIMEFRAME, count=Config.CANDLE_COUNT)
        candles = completed_candles(raw)
        row = {"instrument": inst, "price": None, "rsi": None, "trend": None,
               "signal": None, "adx": None, "vetoed": False}
        if len(candles) >= 20:
            closes = [_f(c["mid"]["c"]) for c in candles]
            row["price"] = closes[-1]
            rsi = MomentumDetector.calculate_rsi(closes, Config.RSI_PERIOD)
            row["rsi"] = round(rsi, 1) if rsi is not None else None
            row["trend"] = MomentumDetector.detect_trend(candles, Config.TREND_PERIOD)
            a = adx(candles, Config.ADX_PERIOD)
            row["adx"] = round(a) if a is not None else None
            sig = signal_for(candles, inst)
            # Reflect what the bot would actually do: the analyzer can veto.
            if sig and Config.ANALYZER and not MarketAnalyzer.approves(candles, inst):
                row["vetoed"] = True
                sig = None
            row["signal"] = sig
        rows.append(row)
    return rows


def _oanda_trades(limit=12):
    files = sorted(glob.glob(str(Config.LOG_DIR / "trades_*.json")))
    if not files:
        return []
    try:
        with open(files[-1]) as fh:
            return json.load(fh)[-limit:][::-1]
    except Exception:
        return []


def _bot_running():
    logs = glob.glob(str(Config.LOG_DIR / "bot_*.log"))
    if not logs:
        return False
    newest = max(os.path.getmtime(p) for p in logs)
    return (time.time() - newest) < max(2 * Config.POLL_INTERVAL, 90)


def build_oanda_venue(client) -> dict:
    label = "OANDA · Forex"
    if client is None:
        return {"label": label, "status": "not_configured",
                "reason": "No OANDA token (OANDA_API_TOKEN / oanda_config.py)."}
    account = _oanda_account(client)
    if not account:
        return {"label": label, "status": "error",
                "error": "Could not reach OANDA (check token / account id)."}
    return {
        "label": label, "status": "ok",
        "env": "LIVE" if Config.is_live_endpoint() else "DEMO",
        "strategy": Config.STRATEGY, "bot_running": _bot_running(),
        "meta": {"risk": Config.RISK_PER_TRADE, "sl": Config.STOP_LOSS_PIPS,
                 "tp": Config.TAKE_PROFIT_PIPS, "pairs": len(Config.INSTRUMENTS)},
        "account": account,
        "positions": _oanda_positions(client),
        "market": _oanda_market(client),
        "trades": _oanda_trades(),
    }


# ---------------------------------------------------------------------------
# Kalshi venue
# ---------------------------------------------------------------------------


def build_kalshi_venue(client) -> dict:
    label = "Kalshi · Event Contracts"
    if client is None:
        return {"label": label, "status": "not_configured",
                "reason": "No Kalshi credentials (KALSHI_API_KEY_ID / KALSHI_PRIVATE_KEY_PATH)."}
    try:
        cents = client.get_balance_cents()
        positions = client.get_positions()
    except Exception as e:
        return {"label": label, "status": "error", "error": str(e)}
    return {
        "label": label, "status": "ok",
        "account": {"balance": cents / 100.0, "currency": "USD"},
        "positions": [
            {"ticker": p.ticker, "quantity": p.quantity,
             "avgPriceCents": p.avg_price_cents, "exposure": p.exposure_cents / 100.0}
            for p in positions
        ],
    }


# ---------------------------------------------------------------------------
# Combined state
# ---------------------------------------------------------------------------


def build_state(oanda_client, kalshi_client) -> dict:
    return {
        "status": "ok",
        "time": datetime.now(timezone.utc).isoformat(),
        "venues": {
            "oanda": build_oanda_venue(oanda_client),
            "kalshi": build_kalshi_venue(kalshi_client),
        },
    }


def _make_clients():
    token = ot._load_api_token()
    oanda = OandaClient(token) if token else None

    kalshi = None
    try:
        from kalshi_trader.client import KalshiClient
        from kalshi_trader.config import Config as KConfig
        kcfg = KConfig.from_env()
        if kcfg.api_key_id and kcfg.private_key_path:
            kalshi = KalshiClient(kcfg)
    except Exception:
        kalshi = None
    return oanda, kalshi


def refresher():
    oanda_client, kalshi_client = _make_clients()
    while True:
        try:
            state = build_state(oanda_client, kalshi_client)
        except Exception as e:
            state = {"status": "error", "error": str(e),
                     "time": datetime.now(timezone.utc).isoformat()}
        with _LOCK:
            _STATE.clear()
            _STATE.update(state)
        time.sleep(REFRESH)


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

INDEX_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Project Titan — Dashboard</title>
<style>
  /* Neon terminal palette: neon green, black, grey (single-theme by design). */
  :root{--bg:#000000;--card:#0c100e;--line:#1c231f;--fg:#cdd6d1;--mut:#8f9995;
        --green:#39ff14;--red:#8f9995;--amber:#8f9995;--blue:#39ff14;--purple:#57e06a;}
  *{box-sizing:border-box}
  body{margin:0;color:var(--fg);
    background:radial-gradient(1100px 460px at 50% -12%, #08120a 0%, var(--bg) 62%);
    font:14px/1.5 ui-monospace,"SF Mono",SFMono-Regular,Menlo,Consolas,monospace}
  header{display:flex;align-items:center;gap:12px;padding:16px 22px;border-bottom:1px solid var(--line)}
  header h1{font-size:16px;margin:0;font-weight:700;letter-spacing:.14em;color:var(--green);
    text-shadow:0 0 16px rgba(57,255,20,.45)}
  .card .v, .pos{text-shadow:0 0 12px rgba(57,255,20,.18)}
  .pill{font-size:11px;padding:2px 9px;border-radius:999px;border:1px solid var(--line);color:var(--mut)}
  .pill.on{color:var(--green);border-color:var(--green)}
  .pill.demo{color:var(--blue);border-color:var(--blue)}
  .pill.warn{color:var(--amber);border-color:var(--amber)}
  .wrap{padding:20px 22px;max-width:1100px;margin:0 auto}
  section.venue{margin-bottom:34px}
  .vhead{display:flex;align-items:center;gap:12px;margin:0 0 14px}
  .vhead h2{font-size:15px;margin:0;font-weight:650}
  .vhead .kalshi{color:var(--purple)}
  .cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin-bottom:16px}
  .card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:13px 15px}
  .card .k{font-size:11px;text-transform:uppercase;letter-spacing:.6px;color:var(--mut)}
  .card .v{font-size:21px;font-weight:650;margin-top:5px}
  h3{font-size:11px;text-transform:uppercase;letter-spacing:.7px;color:var(--mut);margin:16px 0 8px}
  table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden}
  th,td{text-align:right;padding:8px 12px;border-bottom:1px solid var(--line);font-variant-numeric:tabular-nums}
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
  .note{background:var(--card);border:1px dashed var(--line);border-radius:10px;padding:14px 16px;color:var(--mut)}
  .foot{color:var(--mut);font-size:12px;margin-top:12px}
  .dot{width:8px;height:8px;border-radius:50%;display:inline-block;margin-right:5px;vertical-align:middle}
  .dot.g{background:var(--green)} .dot.r{background:var(--red)}
  /* JARVIS wireframe globe */
  .globe-wrap{display:flex;flex-direction:column;align-items:center;justify-content:center;
    padding:26px 0 10px;position:relative}
  #globe{width:260px;height:260px;max-width:64vw;max-height:64vw;display:block}
  .globe-label{margin-top:2px;font-size:10px;letter-spacing:.46em;text-transform:uppercase;
    color:rgba(57,255,20,.65);text-shadow:0 0 10px rgba(57,255,20,.4)}
  .globe-sub{font-size:10px;letter-spacing:.2em;color:var(--mut);margin-top:3px}
  .botbtn{margin-top:16px;font-family:inherit;font-size:12px;letter-spacing:.16em;
    text-transform:uppercase;cursor:pointer;padding:9px 24px;border-radius:999px;
    background:transparent;border:1px solid var(--green);color:var(--green);transition:.15s}
  .botbtn:hover{background:rgba(57,255,20,.09);box-shadow:0 0 16px rgba(57,255,20,.4)}
  .botbtn.running{background:rgba(57,255,20,.15);box-shadow:0 0 14px rgba(57,255,20,.35);font-weight:700}
  .botbtn:disabled{opacity:.5;cursor:default;box-shadow:none}
  .botbtn:focus-visible{outline:2px solid var(--green);outline-offset:3px}
</style></head>
<body>
<header>
  <h1>🤖 Project Titan</h1>
  <span id="clock" class="pill">—</span>
</header>
<div class="globe-wrap">
  <canvas id="globe" aria-label="System status globe" role="img"></canvas>
  <div class="globe-label">Titan Core</div>
  <div class="globe-sub" id="globe-sub">initializing…</div>
  <button id="botbtn" class="botbtn" onclick="botControl()">▶ Start Bot</button>
</div>
<div class="wrap">
  <section class="venue" id="oanda"></section>
  <section class="venue" id="kalshi"></section>
</div>
<script>
const money=(n,d=2)=>(n<0?'-$':'$')+Math.abs(n).toLocaleString(undefined,{minimumFractionDigits:d,maximumFractionDigits:d});
const pnl=n=>`<span class="${n>0?'pos':n<0?'neg':'mut'}">${money(n)}</span>`;
const esc=s=>String(s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
function rsiCls(v){if(v==null)return'mut';if(v<30)return'rsi-lo';if(v>70)return'rsi-hi';return'';}
function trend(t){if(t==='UP')return'<span class="up">▲ up</span>';if(t==='DOWN')return'<span class="down">▼ down</span>';return'<span class="mut">— flat</span>';}
function sig(s){if(s==='BUY')return'<span class="tag buy">BUY</span>';if(s==='SELL')return'<span class="tag sell">SELL</span>';return'<span class="tag none">—</span>';}

function renderOanda(v){
  const head=`<div class="vhead"><h2>💱 ${esc(v.label)}</h2>`+statusPill(v)+`</div>`;
  if(v.status==='not_configured') return head+`<div class="note">${esc(v.reason)}</div>`;
  if(v.status==='error') return head+`<div class="note">⚠ ${esc(v.error)}</div>`;
  const a=v.account, m=v.meta;
  const bot=`<span class="pill ${v.bot_running?'on':'warn'}"><span class="dot ${v.bot_running?'g':'r'}"></span>bot ${v.bot_running?'running':'stopped'}</span>`;
  const cards=[['Balance',money(a.balance)],['NAV',money(a.nav)],['Unrealized P/L',pnl(a.unrealizedPL)],
    ['Realized P/L',pnl(a.realizedPL)],['Open trades',a.openTradeCount],['Margin used',money(a.marginUsed)]]
    .map(([k,val])=>`<div class="card"><div class="k">${k}</div><div class="v">${val}</div></div>`).join('');
  const pos=v.positions.length?v.positions.map(p=>`<tr><td>${p.instrument}</td><td>${p.units}</td><td>${p.avgPrice||'—'}</td><td>${pnl(p.unrealizedPL)}</td></tr>`).join(''):'<tr><td colspan="4" class="mut">No open positions</td></tr>';
  const adxCell=r=>r.adx==null?'<span class="mut">—</span>':`<span class="${r.adx>=25?'pos':'mut'}">${r.adx}</span>`;
  const sigCell=r=>r.vetoed?'<span class="tag none" title="analyzer veto">⊘ veto</span>':sig(r.signal);
  const mk=v.market.map(r=>`<tr><td>${r.instrument}</td><td>${r.price??'—'}</td><td class="${rsiCls(r.rsi)}">${r.rsi??'—'}</td><td>${adxCell(r)}</td><td>${trend(r.trend)}</td><td>${sigCell(r)}</td></tr>`).join('');
  const tr=v.trades.length?v.trades.map(t=>`<tr><td>${new Date(t.timestamp).toLocaleTimeString()}</td><td>${t.instrument}</td><td>${t.direction}</td><td>${t.units}</td><td>${(+t.entry_price).toFixed(5)}</td></tr>`).join(''):'<tr><td colspan="5" class="mut">No trades logged yet</td></tr>';
  return head+`<div class="cards" style="margin-bottom:8px">${cards}</div>`+
    `<div class="foot">${bot} &nbsp; Strategy: <b>${esc(v.strategy)}</b> · Risk $${m.risk}/trade · SL ${m.sl}/TP ${m.tp} pips · ${m.pairs} pairs · ${esc(v.env)}</div>`+
    `<h3>Open positions</h3><table><thead><tr><th>Instrument</th><th>Units</th><th>Avg price</th><th>Unrealized P/L</th></tr></thead><tbody>${pos}</tbody></table>`+
    `<h3>Live signals</h3><table><thead><tr><th>Pair</th><th>Price</th><th>RSI</th><th>ADX</th><th>Trend</th><th>Signal</th></tr></thead><tbody>${mk}</tbody></table>`+
    `<h3>Recent trades</h3><table><thead><tr><th>Time</th><th>Instrument</th><th>Dir</th><th>Units</th><th>Entry</th></tr></thead><tbody>${tr}</tbody></table>`;
}

function renderKalshi(v){
  const head=`<div class="vhead"><h2 class="kalshi">🎲 ${esc(v.label)}</h2>`+statusPill(v)+`</div>`;
  if(v.status==='not_configured') return head+`<div class="note">${esc(v.reason)}<br>Add Kalshi API credentials to watch it here.</div>`;
  if(v.status==='error') return head+`<div class="note">⚠ ${esc(v.error)}</div>`;
  const a=v.account;
  const cards=`<div class="card"><div class="k">Balance</div><div class="v">${money(a.balance)}</div></div>`;
  const pos=v.positions.length?v.positions.map(p=>`<tr><td>${esc(p.ticker)}</td><td>${p.quantity}</td><td>${p.avgPriceCents}¢</td><td>${money(p.exposure)}</td></tr>`).join(''):'<tr><td colspan="4" class="mut">No open positions</td></tr>';
  return head+`<div class="cards" style="margin-bottom:8px">${cards}</div>`+
    `<h3>Open positions</h3><table><thead><tr><th>Ticker</th><th>Contracts</th><th>Avg price</th><th>Exposure</th></tr></thead><tbody>${pos}</tbody></table>`;
}

function statusPill(v){
  if(v.status==='ok') return `<span class="pill ${v.env==='DEMO'?'demo':'on'}">${v.env||'connected'}</span>`;
  if(v.status==='not_configured') return `<span class="pill">not configured</span>`;
  return `<span class="pill warn">error</span>`;
}

async function tick(){
  let s; try{ s=await (await fetch('/api/state')).json(); }catch(e){ window.__titanLive=false; return; }
  if(!s.venues){ return; }
  document.getElementById('clock').textContent = s.time? new Date(s.time).toLocaleTimeString():'—';
  document.getElementById('oanda').innerHTML = renderOanda(s.venues.oanda);
  document.getElementById('kalshi').innerHTML = renderKalshi(s.venues.kalshi);
  const o=s.venues.oanda||{};
  window.__titanLive = o.status==='ok';
  const running = o.status==='ok' && !!o.bot_running;
  window.__botRunning = running;
  const sub=document.getElementById('globe-sub');
  if(sub) sub.textContent = o.status==='ok'
    ? `${running?'● live':'○ idle'} · ${money(o.account?.balance||0,0)}`
    : (o.status==='not_configured'?'awaiting credentials':'connection error');
  const btn=document.getElementById('botbtn');
  if(btn && !btn.disabled){
    btn.textContent = running ? '■ Stop Bot' : '▶ Start Bot';
    btn.classList.toggle('running', running);
  }
}

async function botControl(){
  const btn=document.getElementById('botbtn');
  const running=window.__botRunning;
  btn.disabled=true; btn.textContent='…';
  try{ await fetch(running?'/api/bot/stop':'/api/bot/start',{method:'POST'}); }catch(e){}
  setTimeout(()=>{ btn.disabled=false; tick(); }, 1400);
}

/* ---- JARVIS hollow wireframe globe (Canvas, self-contained) ---- */
(function(){
  const cv=document.getElementById('globe'); if(!cv) return;
  const ctx=cv.getContext('2d');
  const reduce=window.matchMedia('(prefers-reduced-motion:reduce)').matches;
  const PAR=8, MER=12, SEG=46, TILT=-0.38;
  let W=0,H=0,R=0;
  function resize(){
    const dpr=Math.min(window.devicePixelRatio||1,2);
    const size=cv.clientWidth||260;
    cv.width=size*dpr; cv.height=size*dpr;
    ctx.setTransform(dpr,0,0,dpr,0,0);
    W=size; H=size; R=size*0.40;
  }
  resize(); window.addEventListener('resize',resize);
  function proj(lat,lon,rot){
    const cl=Math.cos(lat);
    let x=cl*Math.sin(lon), y=Math.sin(lat), z=cl*Math.cos(lon);
    const xr=x*Math.cos(rot)+z*Math.sin(rot), zr=-x*Math.sin(rot)+z*Math.cos(rot);
    const yt=y*Math.cos(TILT)-zr*Math.sin(TILT), zt=y*Math.sin(TILT)+zr*Math.cos(TILT);
    return {x:W/2+xr*R, y:H/2+yt*R, z:zt};
  }
  function seg(a,b){
    const z=(a.z+b.z)/2, front=z>0;           // hollow: back lines faint -> see-through
    ctx.strokeStyle=`rgba(57,255,20,${front?0.55:0.11})`;
    ctx.lineWidth=front?1.1:0.7;
    ctx.beginPath(); ctx.moveTo(a.x,a.y); ctx.lineTo(b.x,b.y); ctx.stroke();
  }
  let rot=0;
  function frame(){
    ctx.clearRect(0,0,W,H);
    const live=window.__titanLive;
    // outer silhouette ring with glow
    ctx.save();
    ctx.strokeStyle=`rgba(57,255,20,${live?0.6:0.32})`;
    ctx.shadowColor='#39ff14'; ctx.shadowBlur=live?20:10; ctx.lineWidth=1.5;
    ctx.beginPath(); ctx.arc(W/2,H/2,R,0,Math.PI*2); ctx.stroke();
    ctx.restore();
    // parallels
    for(let i=1;i<PAR;i++){
      const lat=-Math.PI/2+i*Math.PI/PAR;
      for(let s=0;s<SEG;s++)
        seg(proj(lat,s/SEG*2*Math.PI,rot), proj(lat,(s+1)/SEG*2*Math.PI,rot));
    }
    // meridians (pole-to-pole half circles around the sphere)
    for(let j=0;j<MER;j++){
      const lon=j*2*Math.PI/MER;
      for(let s=0;s<SEG;s++){
        const l1=-Math.PI/2+s/SEG*Math.PI, l2=-Math.PI/2+(s+1)/SEG*Math.PI;
        seg(proj(l1,lon,rot), proj(l2,lon,rot));
      }
    }
    // core glow
    ctx.save();
    const g=ctx.createRadialGradient(W/2,H/2,0,W/2,H/2,R*0.5);
    g.addColorStop(0,`rgba(57,255,20,${live?0.16:0.07})`); g.addColorStop(1,'rgba(57,255,20,0)');
    ctx.fillStyle=g; ctx.beginPath(); ctx.arc(W/2,H/2,R*0.5,0,Math.PI*2); ctx.fill();
    ctx.restore();
    rot += reduce?0:(live?0.006:0.0028);
    requestAnimationFrame(frame);
  }
  frame();
})();

tick(); setInterval(tick, 3000);
</script>
</body></html>"""


# ---------------------------------------------------------------------------
# Bot control (Start/Stop button backend)
# ---------------------------------------------------------------------------

# Command the Start button launches. Override with DASHBOARD_BOT_CMD to point at
# a different config/bot; it inherits this process's environment (.env, etc.).
BOT_CMD = os.getenv("DASHBOARD_BOT_CMD", "python3 oanda_trader.py")
_BOT_PROC = None
_BOT_LOCK = threading.Lock()


def start_bot():
    global _BOT_PROC
    with _BOT_LOCK:
        if _BOT_PROC is not None and _BOT_PROC.poll() is None:
            return True, "bot already running"
        # clear a leftover kill switch so the new run isn't stopped instantly
        try:
            if os.path.exists(Config.KILL_SWITCH_FILE):
                os.remove(Config.KILL_SWITCH_FILE)
        except OSError:
            pass
        try:
            _BOT_PROC = subprocess.Popen(shlex.split(BOT_CMD))
        except Exception as e:
            return False, f"failed to start: {e}"
        return True, "bot started"


def stop_bot():
    """Clean stop via the kill switch (works even if we didn't launch it)."""
    try:
        open(Config.KILL_SWITCH_FILE, "w").close()
    except OSError:
        pass
    with _BOT_LOCK:
        if _BOT_PROC is not None and _BOT_PROC.poll() is None:
            try:
                _BOT_PROC.terminate()
            except Exception:
                pass
    return "stop requested (kill switch set)"


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

    def do_POST(self):
        # Control endpoints change trading state, so restrict them to localhost —
        # exposing the dashboard on a network must never let others start the bot.
        host = self.client_address[0] if self.client_address else ""
        if host not in ("127.0.0.1", "::1", "localhost"):
            self._send(403, b'{"error":"control is localhost-only"}', "application/json")
            return
        if self.path.startswith("/api/bot/start"):
            ok, msg = start_bot()
            self._send(200, json.dumps({"ok": ok, "message": msg}).encode(), "application/json")
        elif self.path.startswith("/api/bot/stop"):
            self._send(200, json.dumps({"ok": True, "message": stop_bot()}).encode(), "application/json")
        else:
            self._send(404, b"not found", "text/plain")

    def log_message(self, *args):
        pass


def main():
    threading.Thread(target=refresher, daemon=True).start()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"Dashboard on http://localhost:{PORT}  (refresh {REFRESH}s, Ctrl-C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard stopped.")


if __name__ == "__main__":
    main()
