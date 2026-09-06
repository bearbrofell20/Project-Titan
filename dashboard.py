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


def _probation_standing() -> dict | None:
    """Read the OANDA bot's testing-week scorecard, if a trial is under way."""
    try:
        from probation import Probation, ProbationConfig
        prob = Probation(ProbationConfig.from_env(), Config.LOG_DIR)
        if prob.state is None:
            return None
        cfg, st = prob.cfg, prob.state
        elapsed = prob.days_elapsed()
        pnl = prob.pnl()
        passing = pnl >= cfg.min_pnl and st.trades >= cfg.min_trades
        return {
            "verdict": st.verdict,                  # on_trial | passed | failed
            "locked": prob.is_locked(),
            "day": round(elapsed, 2),
            "trial_days": cfg.trial_days,
            "days_left": round(max(0.0, cfg.trial_days - elapsed), 2),
            "pnl": round(pnl, 2),
            "min_pnl": cfg.min_pnl,
            "trades": st.trades,
            "min_trades": cfg.min_trades,
            "passing": passing,
            "baseline_nav": round(st.baseline_nav, 2),
        }
    except Exception:
        return None


def _news_feed() -> dict | None:
    """Latest classified news (from news_bot.py), trimmed for the dashboard."""
    try:
        import news
        feed = news.load_feed(Config.LOG_DIR / "news_feed.json")
        if not feed:
            return None
        return {
            "updated": feed.get("updated"),
            "risk": feed.get("risk", {}),
            "sources": feed.get("sources", []),
            "headlines": feed.get("headlines", [])[:8],
        }
    except Exception:
        return None


def _ledger_scorecard() -> dict | None:
    """One-year test scorecard from the closed-trade ledger (the real progress).

    Reports measured outcomes only, plus progress against the PASS criteria
    pre-registered in project/ONE_YEAR_TEST.md. Never asserts an edge exists —
    at small samples it reports that the result is not yet conclusive.
    """
    try:
        from oanda_trader import TradeLedger
        led = TradeLedger(Config.LOG_DIR)
        s = led.stats()
        if not s.get("trades"):
            return {"trades": 0}
        rows = led.rows
        # peak-to-trough drawdown of the realized equity curve, in dollars
        eq = peak = dd = 0.0
        for r in rows:
            eq += r.get("realized_pl", 0.0)
            peak = max(peak, eq)
            dd = max(dd, peak - eq)
        pf = s.get("profit_factor")
        target_trades = 150
        return {
            "trades": s["trades"],
            "wins": s["wins"],
            "losses": s["losses"],
            "win_rate": s["win_rate"],
            "net_pl": s["net_pl"],
            "profit_factor": pf,
            "expectancy_r": s["expectancy_r"],
            "max_dd": round(dd, 2),
            "target_trades": target_trades,
            "progress_pct": round(min(100.0, 100.0 * s["trades"] / target_trades), 1),
            # PASS gates from ONE_YEAR_TEST.md §4
            "gate_trades": s["trades"] >= target_trades,
            "gate_expectancy": s["expectancy_r"] > 0,
            "gate_pf": (pf is not None and pf >= 1.15),
            "conclusive": s["trades"] >= 150,
        }
    except Exception:
        return None


def build_state(oanda_client, kalshi_client) -> dict:
    return {
        "status": "ok",
        "time": datetime.now(timezone.utc).isoformat(),
        "bots": {"oanda": bot_proc_running("oanda"), "kalshi": bot_proc_running("kalshi")},
        "probation": _probation_standing(),
        "ledger": _ledger_scorecard(),
        "news": _news_feed(),
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
<title>Project Titan — Core</title>
<style>
  /* JARVIS HUD — committed single-theme dark control surface. */
  :root{
    --bg:#02060a; --bg2:#030b12; --panel:rgba(8,26,14,.72); --line:rgba(57,255,20,.16);
    --cyan:#39ff14; --cyan-soft:rgba(57,255,20,.62); --cyan-dim:rgba(57,255,20,.28);
    --amber:#ffe14d; --green:#33ff9e; --red:#ff5c6a; --fg:#cdefd1; --mut:#5f8496;
    --glow:0 0 18px rgba(57,255,20,.45);
  }
  *{box-sizing:border-box}
  html,body{margin:0;height:100%}
  body{background:
      radial-gradient(1200px 700px at 50% -10%, #04160a 0%, rgba(2,6,10,0) 60%),
      repeating-linear-gradient(0deg, rgba(57,255,20,.035) 0 1px, transparent 1px 3px),
      var(--bg);
    color:var(--fg); font:13px/1.5 ui-monospace,"SF Mono",SFMono-Regular,Menlo,Consolas,monospace;
    letter-spacing:.02em; overflow-x:hidden;}
  /* faint moving scanline */
  body::after{content:"";position:fixed;left:0;right:0;height:120px;pointer-events:none;z-index:60;
    background:linear-gradient(180deg,rgba(57,255,20,0),rgba(57,255,20,.06),rgba(57,255,20,0));
    animation:scan 7s linear infinite;}
  @keyframes scan{0%{top:-120px}100%{top:100%}}
  @media (prefers-reduced-motion:reduce){body::after{animation:none;display:none}}
  /* corner brackets */
  .bracket{position:fixed;width:34px;height:34px;border:2px solid var(--cyan-dim);z-index:50;pointer-events:none}
  .bracket.tl{top:10px;left:10px;border-right:0;border-bottom:0}
  .bracket.tr{top:10px;right:10px;border-left:0;border-bottom:0}
  .bracket.bl{bottom:10px;left:10px;border-right:0;border-top:0}
  .bracket.br{bottom:10px;right:10px;border-left:0;border-top:0}

  header{display:flex;align-items:center;gap:14px;padding:16px 26px;border-bottom:1px solid var(--line);
    text-transform:uppercase}
  header h1{font-size:14px;margin:0;font-weight:700;letter-spacing:.42em;color:var(--cyan);
    text-shadow:var(--glow)}
  .sys{font-size:10px;letter-spacing:.28em;color:var(--mut)}
  .spacer{flex:1}
  .stat{display:flex;align-items:center;gap:7px;font-size:10px;letter-spacing:.26em;color:var(--cyan-soft)}
  .live-dot{width:8px;height:8px;border-radius:50%;background:var(--cyan);box-shadow:var(--glow);
    animation:pulse 1.6s ease-in-out infinite}
  .live-dot.off{background:var(--mut);box-shadow:none;animation:none}
  @keyframes pulse{0%,100%{opacity:1}50%{opacity:.25}}
  #clock{font-size:10px;letter-spacing:.2em;color:var(--mut)}

  .wrap{max-width:1180px;margin:0 auto;padding:22px 22px 70px}

  /* --- reactor hero --- */
  .hero{display:flex;flex-direction:column;align-items:center;padding:14px 0 6px;position:relative}
  #reactor{width:340px;height:340px;max-width:78vw;max-height:78vw;display:block}
  .core-read{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);text-align:center;pointer-events:none}
  .core-read .lbl{font-size:9px;letter-spacing:.5em;color:var(--cyan-soft);text-transform:uppercase}
  .core-read .big{font-size:26px;font-weight:700;color:#eaffea;text-shadow:var(--glow);margin-top:4px;
    font-variant-numeric:tabular-nums}
  .core-read .sub{font-size:10px;letter-spacing:.24em;color:var(--mut);margin-top:4px;text-transform:uppercase}
  .ctl{display:flex;gap:12px;margin-top:14px;flex-wrap:wrap;justify-content:center}
  .btn{font:inherit;font-size:11px;letter-spacing:.2em;text-transform:uppercase;cursor:pointer;
    padding:9px 22px;background:rgba(57,255,20,.06);border:1px solid var(--cyan-dim);color:var(--cyan);
    clip-path:polygon(8px 0,100% 0,100% calc(100% - 8px),calc(100% - 8px) 100%,0 100%,0 8px);transition:.15s}
  .btn:hover{background:rgba(57,255,20,.16);box-shadow:var(--glow)}
  .btn.on{background:rgba(51,255,158,.14);border-color:var(--green);color:var(--green);
    box-shadow:0 0 16px rgba(51,255,158,.4);font-weight:700}
  .btn:focus-visible{outline:2px solid var(--cyan);outline-offset:3px}

  /* --- gauge pods --- */
  .pods{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:14px;margin:26px 0 6px}
  .pod{position:relative;aspect-ratio:1;display:flex;flex-direction:column;align-items:center;justify-content:center;
    border-radius:50%;text-align:center;
    background:radial-gradient(circle at 50% 50%, rgba(57,255,20,.05), rgba(2,6,10,0) 70%);}
  .pod::before{content:"";position:absolute;inset:0;border-radius:50%;
    background:var(--ring, conic-gradient(var(--cyan) 0deg, rgba(57,255,20,.10) 0deg));
    -webkit-mask:radial-gradient(farthest-side,transparent calc(100% - 6px),#000 calc(100% - 6px));
            mask:radial-gradient(farthest-side,transparent calc(100% - 6px),#000 calc(100% - 6px));
    filter:drop-shadow(0 0 6px rgba(57,255,20,.5));}
  .pod::after{content:"";position:absolute;inset:9px;border-radius:50%;border:1px solid var(--line)}
  .pod .k{font-size:8.5px;letter-spacing:.22em;color:var(--mut);text-transform:uppercase;z-index:1}
  .pod .v{font-size:18px;font-weight:700;color:#eaffea;z-index:1;margin-top:3px;font-variant-numeric:tabular-nums;
    text-shadow:0 0 12px rgba(57,255,20,.35)}
  .pod .v.pos{color:var(--green);text-shadow:0 0 12px rgba(51,255,158,.4)}
  .pod .v.neg{color:var(--red);text-shadow:0 0 12px rgba(255,92,106,.4)}

  /* --- panels --- */
  .grid{display:grid;grid-template-columns:1fr;gap:16px;margin-top:8px}
  @media(min-width:820px){.grid.two{grid-template-columns:1fr 1fr}}
  .panel{position:relative;background:var(--panel);border:1px solid var(--line);
    clip-path:polygon(0 0,calc(100% - 16px) 0,100% 16px,100% 100%,16px 100%,0 calc(100% - 16px));
    padding:14px 16px 16px;overflow:hidden}
  .panel::before{content:"";position:absolute;top:0;left:0;right:0;height:1px;
    background:linear-gradient(90deg,var(--cyan),transparent);opacity:.6}
  .ph{display:flex;align-items:center;gap:10px;margin-bottom:12px}
  .ph h2{font-size:11px;margin:0;letter-spacing:.32em;text-transform:uppercase;color:var(--cyan);font-weight:700}
  .ph .pill{font-size:9px;letter-spacing:.2em;padding:2px 8px;border:1px solid var(--line);border-radius:2px;color:var(--mut);text-transform:uppercase}
  .ph .pill.on{color:var(--cyan);border-color:var(--cyan-dim)}
  .ph .pill.demo{color:var(--amber);border-color:rgba(255,225,77,.4)}
  .ph .pill.warn{color:var(--amber);border-color:rgba(255,225,77,.4)}
  .foot{color:var(--mut);font-size:10px;letter-spacing:.08em;margin-top:10px;text-transform:uppercase}
  .foot b{color:var(--cyan-soft)}
  .tblwrap{overflow-x:auto}
  table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}
  th,td{text-align:right;padding:7px 10px;border-bottom:1px solid rgba(57,255,20,.08);white-space:nowrap}
  th:first-child,td:first-child{text-align:left}
  th{font-size:9px;text-transform:uppercase;letter-spacing:.18em;color:var(--mut);font-weight:600}
  tbody tr:hover{background:rgba(57,255,20,.05)}
  tr:last-child td{border-bottom:none}
  .pos{color:var(--green)} .neg{color:var(--red)} .mut{color:var(--mut)}
  .up{color:var(--green)} .down{color:var(--red)}
  .rsi-lo{color:var(--green);font-weight:700} .rsi-hi{color:var(--red);font-weight:700}
  .tag{font-size:9px;font-weight:700;padding:2px 8px;letter-spacing:.1em;
    clip-path:polygon(4px 0,100% 0,100% calc(100% - 4px),calc(100% - 4px) 100%,0 100%,0 4px)}
  .tag.buy{background:rgba(51,255,158,.16);color:var(--green)}
  .tag.sell{background:rgba(255,92,106,.16);color:var(--red)}
  .tag.none{color:var(--mut)}
  .note{color:var(--mut);font-size:11px;letter-spacing:.06em}

  /* --- probation --- */
  .trial-top{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:10px}
  .trial-verdict{font-size:11px;font-weight:700;letter-spacing:.14em}
  .trial-verdict.passing{color:var(--green)} .trial-verdict.failing{color:var(--amber)}
  .trial-verdict.locked{color:var(--red)}
  .trial-bar{height:6px;background:rgba(57,255,20,.08);border:1px solid var(--line);overflow:hidden}
  .trial-bar>i{display:block;height:100%;background:linear-gradient(90deg,var(--cyan-dim),var(--cyan));
    box-shadow:var(--glow);transition:width .5s}
  .trial-grid{display:grid;grid-template-columns:1fr 1fr;gap:7px 20px;margin-top:12px;font-size:11px}
  .trial-grid .k{color:var(--mut);text-transform:uppercase;letter-spacing:.12em;font-size:10px}
  .trial-grid .val{float:right;color:#eaffea;font-variant-numeric:tabular-nums}
</style></head>
<body>
<div class="bracket tl"></div><div class="bracket tr"></div>
<div class="bracket bl"></div><div class="bracket br"></div>
<header>
  <h1>◆ Project Titan</h1>
  <span class="sys">Core · Autonomous Trading</span>
  <span class="spacer"></span>
  <span class="stat"><span id="live-dot" class="live-dot off"></span><span id="live-txt">initializing</span></span>
  <span id="clock">—</span>
</header>

<div class="hero">
  <canvas id="reactor" aria-label="Titan core reactor" role="img"></canvas>
  <div class="core-read">
    <div class="lbl">Titan Core</div>
    <div class="big" id="core-balance">—</div>
    <div class="sub" id="core-status">standby</div>
  </div>
  <div class="ctl">
    <button id="btn-oanda" class="btn" onclick="botControl('oanda')">▶ Forex Bot</button>
    <button id="btn-kalshi" class="btn" onclick="botControl('kalshi')">▶ Kalshi Bot</button>
  </div>
</div>

<div class="wrap">
  <div class="pods" id="pods"></div>
  <div id="scorecard"></div>
  <div id="probation"></div>
  <section id="intel"></section>
  <section id="oanda"></section>
  <section id="kalshi"></section>
</div>

<script>
const money=(n,d=2)=>(n<0?'-$':'$')+Math.abs(+n||0).toLocaleString(undefined,{minimumFractionDigits:d,maximumFractionDigits:d});
const esc=s=>String(s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
const clsPL=n=>n>0?'pos':n<0?'neg':'mut';
function rsiCls(v){if(v==null)return'mut';if(v<30)return'rsi-lo';if(v>70)return'rsi-hi';return'';}
function trend(t){if(t==='UP')return'<span class="up">▲</span>';if(t==='DOWN')return'<span class="down">▼</span>';return'<span class="mut">—</span>';}
function sig(s){if(s==='BUY')return'<span class="tag buy">BUY</span>';if(s==='SELL')return'<span class="tag sell">SELL</span>';return'<span class="tag none">—</span>';}

function pod(k,val,{cls='',pct=null}={}){
  const ring = pct==null
    ? 'conic-gradient(rgba(57,255,20,.25) 0deg, rgba(57,255,20,.08) 0deg)'
    : `conic-gradient(var(--cyan) ${Math.max(0,Math.min(100,pct))*3.6}deg, rgba(57,255,20,.08) 0deg)`;
  return `<div class="pod" style="--ring:${ring}"><div class="k">${k}</div><div class="v ${cls}">${val}</div></div>`;
}

function renderPods(v){
  const el=document.getElementById('pods');
  if(!v||v.status!=='ok'||!v.account){ el.innerHTML=''; return; }
  const a=v.account;
  const marginPct = a.nav>0 ? (a.marginUsed/a.nav*100) : 0;
  const tradePct = 100*Math.min(1,(a.openTradeCount||0)/8);
  el.innerHTML =
    pod('Balance', money(a.balance,0)) +
    pod('NAV', money(a.nav,0)) +
    pod('Unrealized', money(a.unrealizedPL), {cls:clsPL(a.unrealizedPL), pct: Math.min(100,Math.abs(a.unrealizedPL))}) +
    pod('Realized', money(a.realizedPL), {cls:clsPL(a.realizedPL)}) +
    pod('Margin', marginPct.toFixed(1)+'%', {pct:marginPct}) +
    pod('Trades', (a.openTradeCount||0), {pct:tradePct});
}

function statusPill(v){
  if(v.status==='ok') return `<span class="pill ${v.env==='DEMO'?'demo':'on'}">${v.env||'online'}</span>`;
  if(v.status==='not_configured') return `<span class="pill">offline</span>`;
  return `<span class="pill warn">error</span>`;
}

function renderOanda(v){
  const head=`<div class="ph"><h2>▚ ${esc(v.label)}</h2>${statusPill(v)}</div>`;
  if(v.status==='not_configured') return `<div class="panel">${head}<div class="note">${esc(v.reason||'not configured')}</div></div>`;
  if(v.status==='error') return `<div class="panel">${head}<div class="note">⚠ ${esc(v.error)}</div></div>`;
  const m=v.meta;
  const bot=`<span class="pill ${v.bot_running?'on':'warn'}">bot ${v.bot_running?'online':'idle'}</span>`;
  const pos=v.positions.length?v.positions.map(p=>`<tr><td>${p.instrument}</td><td>${p.units}</td><td>${p.avgPrice||'—'}</td><td class="${clsPL(p.unrealizedPL)}">${money(p.unrealizedPL)}</td></tr>`).join(''):'<tr><td colspan="4" class="mut">no open positions</td></tr>';
  const adxCell=r=>r.adx==null?'<span class="mut">—</span>':`<span class="${r.adx>=25?'pos':'mut'}">${r.adx}</span>`;
  const sigCell=r=>r.vetoed?'<span class="tag none">⊘</span>':sig(r.signal);
  const mk=v.market.map(r=>`<tr><td>${r.instrument}</td><td>${r.price??'—'}</td><td class="${rsiCls(r.rsi)}">${r.rsi??'—'}</td><td>${adxCell(r)}</td><td>${trend(r.trend)}</td><td>${sigCell(r)}</td></tr>`).join('');
  const tr=v.trades.length?v.trades.map(t=>`<tr><td>${new Date(t.timestamp).toLocaleTimeString()}</td><td>${t.instrument}</td><td>${esc(t.direction)}</td><td>${t.units}</td><td>${(+t.entry_price).toFixed(5)}</td></tr>`).join(''):'<tr><td colspan="5" class="mut">no trades logged</td></tr>';
  return `<div class="panel">${head}`+
    `<div class="foot">${bot} · strategy <b>${esc(v.strategy)}</b> · risk $${m.risk}/trade · SL ${m.sl}/TP ${m.tp} · ${m.pairs} pairs · ${esc(v.env)}</div>`+
    `<h3 class="foot">Live signals</h3><div class="tblwrap"><table><thead><tr><th>Pair</th><th>Price</th><th>RSI</th><th>ADX</th><th>Trend</th><th>Signal</th></tr></thead><tbody>${mk}</tbody></table></div>`+
    `<h3 class="foot">Open positions</h3><div class="tblwrap"><table><thead><tr><th>Instrument</th><th>Units</th><th>Avg</th><th>Unreal. P/L</th></tr></thead><tbody>${pos}</tbody></table></div>`+
    `<h3 class="foot">Recent trades</h3><div class="tblwrap"><table><thead><tr><th>Time</th><th>Instrument</th><th>Dir</th><th>Units</th><th>Entry</th></tr></thead><tbody>${tr}</tbody></table></div>`+
    `</div>`;
}

function renderKalshi(v){
  const head=`<div class="ph"><h2>◈ ${esc(v.label)}</h2>${statusPill(v)}</div>`;
  if(v.status==='not_configured') return `<div class="panel">${head}<div class="note">${esc(v.reason||'not configured')}</div></div>`;
  if(v.status==='error') return `<div class="panel">${head}<div class="note">⚠ ${esc(v.error)}</div></div>`;
  const a=v.account;
  const pos=v.positions.length?v.positions.map(p=>`<tr><td>${esc(p.ticker)}</td><td>${p.quantity}</td><td>${p.avgPriceCents}¢</td><td>${money(p.exposure)}</td></tr>`).join(''):'<tr><td colspan="4" class="mut">no open positions</td></tr>';
  return `<div class="panel">${head}<div class="foot">balance <b>${money(a.balance)}</b></div>`+
    `<h3 class="foot">Open positions</h3><div class="tblwrap"><table><thead><tr><th>Ticker</th><th>Qty</th><th>Avg</th><th>Exposure</th></tr></thead><tbody>${pos}</tbody></table></div></div>`;
}

function renderScorecard(sc){
  const el=document.getElementById('scorecard');
  if(!sc){ el.innerHTML=''; return; }
  if(!sc.trades){
    el.innerHTML=`<div class="panel" style="margin-bottom:16px">`+
      `<div class="trial-top"><h2 style="font-size:11px;letter-spacing:.32em;margin:0;color:var(--cyan)">`+
      `◇ One-Year Test</h2><span class="trial-verdict failing">AWAITING FIRST CLOSE</span></div>`+
      `<div class="note" style="margin-top:8px">No closed trades recorded yet. `+
      `Scorecard populates as trades finish.</div></div>`;
    return;
  }
  const g=(ok)=>ok?'<span style="color:var(--green)">PASS</span>'
                  :'<span style="color:var(--mut)">pending</span>';
  const verdict = sc.conclusive
      ? (sc.gate_expectancy&&sc.gate_pf ? ['MEETING CRITERIA','passing'] : ['BELOW CRITERIA','failing'])
      : ['SAMPLE TOO SMALL','failing'];
  el.innerHTML=`<div class="panel" style="margin-bottom:16px">`+
    `<div class="trial-top"><h2 style="font-size:11px;letter-spacing:.32em;margin:0;color:var(--cyan)">`+
    `◇ One-Year Test</h2><span class="trial-verdict ${verdict[1]}">${verdict[0]}</span></div>`+
    `<div class="trial-bar"><i style="width:${sc.progress_pct}%"></i></div>`+
    `<div class="trial-grid">`+
      `<div class="k">Closed trades <span class="val">${sc.trades} / ${sc.target_trades}</span></div>`+
      `<div class="k">Net P/L <span class="val ${clsPL(sc.net_pl)}">${money(sc.net_pl)}</span></div>`+
      `<div class="k">Win rate <span class="val">${sc.win_rate}% (${sc.wins}W/${sc.losses}L)</span></div>`+
      `<div class="k">Expectancy <span class="val ${clsPL(sc.expectancy_r)}">${sc.expectancy_r>0?'+':''}${sc.expectancy_r} R</span></div>`+
      `<div class="k">Profit factor <span class="val">${sc.profit_factor!==null?sc.profit_factor:'—'}</span></div>`+
      `<div class="k">Max drawdown <span class="val">${money(sc.max_dd)}</span></div>`+
      `<div class="k">Sample ≥150 <span class="val">${g(sc.gate_trades)}</span></div>`+
      `<div class="k">PF ≥ 1.15 <span class="val">${g(sc.gate_pf)}</span></div>`+
    `</div>`+
    (sc.conclusive?'':`<div class="note" style="margin-top:10px">`+
      `Below 150 trades this result cannot be distinguished from luck — `+
      `it is not yet evidence either way.</div>`)+
    `</div>`;
}

function renderProbation(p){
  const el=document.getElementById('probation');
  if(!p){ el.innerHTML=''; return; }
  const pct=Math.max(0,Math.min(100,(p.day/p.trial_days)*100));
  let vtxt,vcls;
  if(p.verdict==='passed'){ vtxt='◉ PASSED'; vcls='passing'; }
  else if(p.verdict==='failed'){ vtxt='⛓ PURGATORY'; vcls='locked'; }
  else { vtxt=p.passing?'PASSING':'FAILING'; vcls=p.passing?'passing':'failing'; }
  el.innerHTML=`<div class="panel" style="margin-bottom:16px">`+
    `<div class="trial-top"><h2 style="font-size:11px;letter-spacing:.32em;margin:0;color:var(--cyan)">◇ Testing Week</h2>`+
    `<span class="trial-verdict ${vcls}">${vtxt}</span></div>`+
    `<div class="trial-bar"><i style="width:${pct}%"></i></div>`+
    `<div class="trial-grid">`+
      `<div class="k">Day <span class="val">${p.day.toFixed(2)} / ${p.trial_days}</span></div>`+
      `<div class="k">Net P/L <span class="val ${clsPL(p.pnl)}">${money(p.pnl)}</span></div>`+
      `<div class="k">Days left <span class="val">${p.days_left.toFixed(2)}</span></div>`+
      `<div class="k">To pass <span class="val">≥ ${money(p.min_pnl)}</span></div>`+
      `<div class="k">Trades <span class="val">${p.trades} / ≥${p.min_trades}</span></div>`+
      `<div class="k">Baseline <span class="val">${money(p.baseline_nav)}</span></div>`+
    `</div></div>`;
}

function toggleSources(){
  window.__srcOpen=!window.__srcOpen;
  const e=document.getElementById('srclist'); if(e) e.hidden=!window.__srcOpen;
  const b=document.getElementById('srcbtn'); if(b) b.classList.toggle('on',window.__srcOpen);
}
function renderNews(n){
  const el=document.getElementById('intel');
  if(!el) return;
  if(!n){ el.innerHTML=''; return; }
  const r=n.risk||{};
  const lvl=(r.level||'calm');
  const col = lvl==='high'?'var(--red)':lvl==='elevated'?'var(--amber)':'var(--green)';
  const rows=(n.headlines||[]).map(h=>{
    const imp = h.impact==='high'
      ? '<span class="tag sell">HIGH</span>'
      : h.impact==='medium'
        ? '<span class="tag" style="background:rgba(255,225,77,.16);color:var(--amber)">MED</span>'
        : '<span class="tag none">low</span>';
    const ccy=(h.currencies||[]).join(' ')||'—';
    const t=esc(h.title||'');
    const title=h.link?`<a href="${esc(h.link)}" target="_blank" rel="noopener" style="color:var(--fg);text-decoration:none">${t}</a>`:t;
    const flag=h.leader?'<span class="tag" style="background:rgba(255,225,77,.18);color:var(--amber);margin-right:6px">◤ LEADER</span>':'';
    return `<tr><td>${imp}</td><td style="text-align:left;white-space:normal">${flag}${title}</td><td class="mut">${esc(h.source||'')}</td><td class="mut">${ccy}</td></tr>`;
  }).join('') || '<tr><td colspan="4" class="mut">awaiting first scan…</td></tr>';
  const srcRows=(n.sources||[]).map(sc=>
    `<tr><td style="text-align:left"><a href="${esc(sc.url)}" target="_blank" rel="noopener" style="color:var(--cyan);text-decoration:none">${esc(sc.name)}</a></td>`+
    `<td class="mut" style="text-align:left;white-space:normal">${esc(sc.url)}</td><td>${sc.count}</td></tr>`
  ).join('') || '<tr><td colspan="3" class="mut">—</td></tr>';
  el.innerHTML=`<div class="panel" style="margin-bottom:16px"><div class="ph"><h2>◎ World Intel</h2>`+
    `<span class="pill" style="color:${col};border-color:${col}">${lvl.toUpperCase()} · ${(r.posture||'neutral').replace('_','-')}</span>`+
    `<span class="spacer" style="flex:1"></span>`+
    `<button id="srcbtn" class="btn ${window.__srcOpen?'on':''}" style="padding:5px 14px;font-size:10px;margin:0" onclick="toggleSources()">⛁ Sources · ${(n.sources||[]).length}</button></div>`+
    `<div id="srclist" ${window.__srcOpen?'':'hidden'}><div class="tblwrap"><table><thead><tr><th>Source</th><th>Feed</th><th># now</th></tr></thead><tbody>${srcRows}</tbody></table></div>`+
    `<div class="foot">These are every feed the intel is scanned from, refreshed each pass.</div></div>`+
    `<div class="tblwrap" style="margin-top:12px"><table><thead><tr><th>Impact</th><th>Headline</th><th>Source</th><th>FX</th></tr></thead><tbody>${rows}</tbody></table></div>`+
    `<div class="foot">updated ${n.updated?new Date(n.updated).toLocaleTimeString():'—'} · scans every 30 min · defensive risk filter</div></div>`;
}

/* ---- state ---- */
async function tick(){
  let s; try{ s=await (await fetch('/api/state')).json(); }catch(e){ window.__live=false; return; }
  if(!s.venues) return;
  const o=s.venues.oanda||{}, bots=s.bots||{};
  window.__bots=bots; window.__live=o.status==='ok';
  document.getElementById('clock').textContent = s.time? new Date(s.time).toLocaleTimeString():'—';
  const anyOn=bots.oanda||bots.kalshi;
  document.getElementById('live-dot').className='live-dot'+(anyOn?'':' off');
  document.getElementById('live-txt').textContent = o.status==='ok'?(anyOn?'systems online':'standby'):'offline';
  document.getElementById('core-balance').textContent = o.account?money(o.account.balance,0):'—';
  document.getElementById('core-status').textContent = o.status==='ok'?(anyOn?'● live':'○ idle'):'awaiting link';
  renderPods(o);
  renderScorecard(s.ledger);
  renderProbation(s.probation);
  renderNews(s.news);
  document.getElementById('oanda').innerHTML = renderOanda(o);
  document.getElementById('kalshi').innerHTML = renderKalshi(s.venues.kalshi||{});
  [['oanda','Forex Bot'],['kalshi','Kalshi Bot']].forEach(([w,label])=>{
    const b=document.getElementById('btn-'+w); if(!b||b.disabled)return;
    const run=!!bots[w]; b.textContent=(run?'■ Stop ':'▶ Start ')+label; b.classList.toggle('on',run);
  });
}
async function botControl(which){
  const b=document.getElementById('btn-'+which); const run=(window.__bots||{})[which];
  b.disabled=true; b.textContent='…';
  try{ await fetch('/api/bot/'+which+'/'+(run?'stop':'start'),{method:'POST'}); }catch(e){}
  setTimeout(()=>{ b.disabled=false; tick(); },1400);
}

/* ---- arc-reactor core (Canvas) ---- */
(function(){
  const cv=document.getElementById('reactor'); if(!cv) return;
  const ctx=cv.getContext('2d');
  const reduce=matchMedia('(prefers-reduced-motion:reduce)').matches;
  let W,H,R;
  function rs(){const d=Math.min(devicePixelRatio||1,2),s=cv.clientWidth||340;
    cv.width=s*d;cv.height=s*d;ctx.setTransform(d,0,0,d,0,0);W=s;H=s;R=s*0.46;}
  rs(); addEventListener('resize',rs);
  function ring(r,rot,ticks,len,w,a){
    ctx.save();ctx.translate(W/2,H/2);ctx.rotate(rot);
    ctx.strokeStyle=`rgba(57,255,20,${a})`;ctx.lineWidth=w;
    for(let i=0;i<ticks;i++){const ang=i/ticks*Math.PI*2;
      ctx.beginPath();
      ctx.moveTo(Math.cos(ang)*r,Math.sin(ang)*r);
      ctx.lineTo(Math.cos(ang)*(r-len),Math.sin(ang)*(r-len));
      ctx.stroke();}
    ctx.restore();
  }
  function circle(r,a,w){ctx.beginPath();ctx.strokeStyle=`rgba(57,255,20,${a})`;ctx.lineWidth=w||1;
    ctx.arc(W/2,H/2,r,0,7);ctx.stroke();}
  let t=0;
  (function frame(){
    ctx.clearRect(0,0,W,H);
    const live=window.__live;
    const gA=live?1:0.5;
    ctx.save(); ctx.shadowColor='#39ff14'; ctx.shadowBlur=live?16:7;
    circle(R,0.55*gA,1.6);
    circle(R*0.86,0.18*gA,1);
    ctx.restore();
    // outer tick ring (slow CW)
    ring(R*0.99, t*0.15, 90, 8, 1, 0.35*gA);
    // mid heavy ticks (CCW)
    ring(R*0.80, -t*0.35, 36, 16, 2, 0.55*gA);
    // inner fine ring (CW faster)
    ring(R*0.62, t*0.7, 120, 5, 1, 0.28*gA);
    circle(R*0.52,0.4*gA,1);
    // segmented inner arc
    ctx.save();ctx.translate(W/2,H/2);ctx.rotate(-t*0.5);
    ctx.strokeStyle=`rgba(255,225,77,${0.85*gA})`;ctx.lineWidth=3;ctx.shadowColor='#ffe14d';ctx.shadowBlur=12;
    for(let k=0;k<6;k++){const a0=k/6*Math.PI*2, a1=a0+0.7;
      ctx.beginPath();ctx.arc(0,0,R*0.44,a0,a1);ctx.stroke();}
    ctx.restore();
    // core glow + pulse
    const pulse=reduce?0.5:(0.5+0.5*Math.sin(t*2));
    const g=ctx.createRadialGradient(W/2,H/2,0,W/2,H/2,R*0.4);
    g.addColorStop(0,`rgba(200,255,190,${(0.35+0.35*pulse)*gA})`);
    g.addColorStop(0.4,`rgba(57,255,20,${0.22*gA})`);
    g.addColorStop(1,'rgba(57,255,20,0)');
    ctx.fillStyle=g;ctx.beginPath();ctx.arc(W/2,H/2,R*0.4,0,7);ctx.fill();
    // core disc
    ctx.save();ctx.shadowColor='#9fe9ff';ctx.shadowBlur=live?26:12;
    ctx.fillStyle=`rgba(210,255,200,${(0.5+0.3*pulse)*gA})`;
    ctx.beginPath();ctx.arc(W/2,H/2,R*0.12,0,7);ctx.fill();ctx.restore();
    if(!reduce) t+=0.01;
    requestAnimationFrame(frame);
  })();
})();

tick(); setInterval(tick,3000);
</script>
</body></html>"""


# ---------------------------------------------------------------------------
# Bot control (Start/Stop button backend)
# ---------------------------------------------------------------------------

# Each venue's bot: the command the Start button launches (inherits this
# process's environment / .env) and the kill-switch file its Stop button sets.
BOT_CMDS = {
    "oanda": os.getenv("DASHBOARD_OANDA_CMD", "python3 oanda_trader.py"),
    "kalshi": os.getenv("DASHBOARD_KALSHI_CMD", "python3 kalshi_bot.py"),
}
_KILL = {"oanda": Config.KILL_SWITCH_FILE, "kalshi": "KILL_SWITCH_KALSHI.txt"}
_PROCS = {"oanda": None, "kalshi": None}
_BOT_LOCK = threading.Lock()


def bot_proc_running(which: str) -> bool:
    with _BOT_LOCK:
        p = _PROCS.get(which)
        return p is not None and p.poll() is None


def start_bot(which: str):
    if which not in BOT_CMDS:
        return False, f"unknown bot {which!r}"
    with _BOT_LOCK:
        p = _PROCS.get(which)
        if p is not None and p.poll() is None:
            return True, f"{which} already running"
        try:
            if os.path.exists(_KILL[which]):
                os.remove(_KILL[which])   # clear stale kill switch
        except OSError:
            pass
        try:
            _PROCS[which] = subprocess.Popen(shlex.split(BOT_CMDS[which]))
        except Exception as e:
            return False, f"failed to start {which}: {e}"
        return True, f"{which} started"


def stop_bot(which: str):
    """Clean stop via the kill switch (works even if we didn't launch it)."""
    ks = _KILL.get(which)
    if ks:
        try:
            open(ks, "w").close()
        except OSError:
            pass
    with _BOT_LOCK:
        p = _PROCS.get(which)
        if p is not None and p.poll() is None:
            try:
                p.terminate()
            except Exception:
                pass
    return f"{which} stop requested"


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
                state = dict(_STATE)
            # live bot status (not the ~8s-cached snapshot) for responsive buttons
            state["bots"] = {"oanda": bot_proc_running("oanda"),
                             "kalshi": bot_proc_running("kalshi")}
            self._send(200, json.dumps(state).encode(), "application/json")
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
        parts = self.path.split("?")[0].strip("/").split("/")  # api / bot / <which> / <action>
        if len(parts) == 4 and parts[0] == "api" and parts[1] == "bot":
            which, action = parts[2], parts[3]
            if action == "start":
                ok, msg = start_bot(which)
            elif action == "stop":
                ok, msg = True, stop_bot(which)
            else:
                self._send(404, b'{"error":"unknown action"}', "application/json")
                return
            self._send(200, json.dumps({"ok": ok, "message": msg}).encode(), "application/json")
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
