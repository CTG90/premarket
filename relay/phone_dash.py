"""
Make Me Trade — read-only phone dashboard.

The bot serves a small web app on port 8765 (same Wi-Fi, or anywhere via Tailscale).
  /            the phone page (add it to your home screen — it behaves like an app)
  /api/status  the live numbers as JSON (the page refreshes itself every 20 s)
Read-only: there is no way to place, change or cancel anything from here.
Access needs the private key shown in the bot log (…/?k=XXXX); it's stored in bot_config.json as dash_token.
"""
import datetime as dt
import json
import secrets
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

NAMES = {"spread": "Credit spreads", "lotto": "🎰 Lotto calls", "debit": "Dip call spreads", "call": "Dip single calls",
         "etf_trend": "3x S&P trend (sim)", "etf_dip": "3x S&P dip (sim)", "sr": "📐 Support/resistance"}
TARGETS = {"spread": "~75% win · +4-6%/trade", "lotto": "~20% win · 1 in 8 hits 5.8x", "debit": "~57% win · +6-10%/trade",
           "call": "~58% win · ~+15%/trade", "etf_trend": "~17%/yr", "etf_dip": "~12-20%/yr", "sr": "unproven"}
MILESTONES = (15, 20, 25, 30, 40, 50, 75, 100, 150, 200, 300, 500)


def pretty(occ):
    """NVDA261030C00110000 -> NVDA $110 Call · Oct 30 (spreads and sims already read fine)."""
    import re
    m = re.fullmatch(r"([A-Z.]{1,6})(\d{2})(\d{2})(\d{2})([CP])(\d{8})", occ or "")
    if not m:
        return occ
    sym, yy, mm, dd, cp, k = m.groups()
    d = dt.date(2000 + int(yy), int(mm), int(dd))
    return "%s $%g %s · %s" % (sym, int(k) / 1000, "Call" if cp == "C" else "Put", d.strftime("%b ") + str(d.day))   # no %-d: Windows strftime doesn't support it


def lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.connect(("10.255.255.255", 1)); ip = s.getsockname()[0]; s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def snapshot(bot, M):
    """Everything the phone shows, as plain data."""
    st, cfg = bot.st, bot.cfg
    sleeves = []
    for k in (cfg.get("sleeves") or {}):
        cl = [t for t in st["trades"] if t.get("kind") == k and t["status"] == "closed"]
        op = [t for t in st["trades"] if t.get("kind") == k and t["status"] in ("opening", "open", "closing")]
        realized = sum(M.pnl(t) for t in cl); unreal = sum(M.pnl(t) for t in op if t["status"] != "opening")
        start = bot.sleeve_start(k)
        sleeves.append({"key": k, "name": NAMES.get(k, k), "start": start, "balance": round(start + realized + unreal, 2),
                        "realized": round(realized, 2), "open_pl": round(unreal, 2), "open": len(op), "closed": len(cl),
                        "win": round(100 * sum(M.pnl(t) > 0 for t in cl) / len(cl)) if cl else None, "target": TARGETS.get(k, "")})
    pos = []
    for t in st["trades"]:
        if t["status"] not in ("opening", "open", "closing"):
            continue
        exp = t.get("exp") or ""
        try:
            dte = max(0, (dt.date.fromisoformat(exp) - dt.date.today()).days) if exp else None
        except Exception:
            dte = None
        pos.append({"kind": NAMES.get(t.get("kind"), t.get("kind")), "contract": pretty(t["occ"]), "qty": t.get("qty"), "status": t["status"],
                    "entry": t["entry"]["px"], "mark": (t.get("mark") or {}).get("px"), "pl": round(M.pnl(t), 2), "pl_pct": round(M.pnl_pct(t), 1),
                    "best": t.get("mfe"), "worst": t.get("mae"), "hits": [m for m in MILESTONES if t.get("hit_%d" % m)],
                    "exp": exp if not str(t.get("kind", "")).startswith("etf") else "", "dte": dte if not str(t.get("kind", "")).startswith("etf") else None,
                    "why": (t.get("feat") or {}).get("why") or t.get("play")})
    closed = sorted([t for t in st["trades"] if t["status"] == "closed"], key=lambda t: t["exit"]["at"], reverse=True)[:15]
    recent = [{"contract": pretty(t["occ"]), "kind": NAMES.get(t.get("kind"), t.get("kind")), "pl": round(M.pnl(t), 2), "pl_pct": round(M.pnl_pct(t), 1),
               "reason": t["exit"].get("reason"), "best": t.get("mfe"),
               "at": dt.datetime.fromtimestamp(t["exit"]["at"], M.ET).strftime("%a %H:%M")} for t in closed]
    log = [{"at": dt.datetime.fromtimestamp(l["at"], M.ET).strftime("%a %H:%M"), "m": l["m"]} for l in (st.get("log") or [])[-25:]][::-1]
    total_start = sum(s["start"] for s in sleeves); total_bal = sum(s["balance"] for s in sleeves)
    return {"now": dt.datetime.now(M.ET).strftime("%a %b %d %H:%M:%S"),
            "last_cycle": dt.datetime.fromtimestamp(bot.last_tick, M.ET).strftime("%H:%M:%S") if bot.last_tick else None,
            "market": (bot.pb or {}).get("label"), "error": bot.err, "stopped": M.STOP_F.exists(),
            "trial": {"start": cfg.get("trial_started"), "review": cfg.get("trial_review")},
            "total": {"start": total_start, "balance": round(total_bal, 2), "pl": round(total_bal - total_start, 2)},
            "sleeves": sleeves, "positions": pos, "closed": recent, "log": log}


PAGE = r"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name=apple-mobile-web-app-capable content=yes><meta name=apple-mobile-web-app-status-bar-style content=black-translucent>
<meta name=apple-mobile-web-app-title content="Make Me Trade"><meta name=theme-color content="#0b0f17">
<link rel=manifest href="manifest.json?k=__K__"><title>Make Me Trade</title>
<style>
:root{--bg:#0b0f17;--card:#121826;--line:#1f2a3d;--txt:#e6ebf5;--mut:#7d8aa5;--up:#22c55e;--dn:#ef4444;--acc:#60a5fa}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--txt);font:15px/1.4 -apple-system,system-ui,Segoe UI,Roboto,sans-serif;padding:max(14px,env(safe-area-inset-top)) 14px 40px}
h1{font-size:20px;margin:0}h2{font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:var(--mut);margin:18px 2px 6px}
.c{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:12px 14px;margin-bottom:8px}
.row{display:flex;justify-content:space-between;align-items:baseline;gap:8px}.m{color:var(--mut);font-size:12px}
.big{font-size:28px;font-weight:700}.up{color:var(--up)}.dn{color:var(--dn)}.b{font-weight:600}
.chip{display:inline-block;font-size:11px;padding:1px 7px;border-radius:99px;background:#1b2436;color:var(--mut);margin:3px 4px 0 0}
.hit{background:rgba(34,197,94,.15);color:var(--up)}button{background:var(--acc);color:#04101f;border:0;border-radius:10px;padding:8px 14px;font-weight:600;font-size:14px}
.err{border-color:#7f1d1d;color:#fca5a5}.log{font-size:12px;border-bottom:1px solid var(--line);padding:6px 0}.log:last-child{border:0}
</style></head><body>
<div class=row><h1>📈 Make Me Trade</h1><button onclick="load(1)">↻</button></div>
<div class=m id=stamp>loading…</div>
<div id=app></div>
<script>
const K=new URLSearchParams(location.search).get('k')||'';
const $=(n,d=0)=>n==null?'--':(n<0?'-':'')+'$'+Math.abs(n).toFixed(d).replace(/\B(?=(\d{3})+(?!\d))/g,',');
const pct=n=>n==null?'--':(n>0?'+':'')+n.toFixed(0)+'%';const cls=n=>n>0?'up':n<0?'dn':'';
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
async function load(manual){
 try{const r=await fetch('api/status?k='+encodeURIComponent(K),{cache:'no-store'});
  if(r.status==403){document.getElementById('app').innerHTML='<div class="c err">Wrong or missing key. Use the full link from the bot log.</div>';return}
  const d=await r.json();render(d)}catch(e){document.getElementById('stamp').textContent='⚠️ Can\'t reach the bot — is it running and are you on the same network/Tailscale?'}}
function render(d){
 document.getElementById('stamp').textContent='Updated '+d.now+' · bot cycle '+(d.last_cycle||'--')+(d.trial&&d.trial.review?' · trial review '+d.trial.review:'');
 let h='';
 if(d.error)h+='<div class="c err">⚠️ '+esc(d.error)+'</div>';
 if(d.stopped)h+='<div class="c err">⏸ STOP file present — no new entries</div>';
 h+='<div class=c><div class=m>All strategies (paper)</div><div class=row><div class="big '+cls(d.total.pl)+'">'+$(d.total.balance)+'</div><div class="b '+cls(d.total.pl)+'">'+(d.total.pl>=0?'+':'')+$(d.total.pl)+'</div></div>'+
   '<div class=m>'+esc(d.market||'')+'</div></div>';
 h+='<h2>Scorecard</h2>';
 for(const s of d.sleeves){h+='<div class=c><div class=row><span class=b>'+esc(s.name)+'</span><span class="b '+cls(s.balance-s.start)+'">'+$(s.balance)+'</span></div>'+
   '<div class=row><span class=m>'+s.open+' open · '+s.closed+' closed'+(s.win!=null?' · '+s.win+'% win':'')+'</span><span class=m>'+(s.realized||s.open_pl?((s.realized+s.open_pl)>=0?'+':'')+$(s.realized+s.open_pl):'')+'</span></div>'+
   '<div class=m>target: '+esc(s.target)+'</div></div>'}
 h+='<h2>Open positions ('+d.positions.length+')</h2>';
 if(!d.positions.length)h+='<div class="c m">None right now.</div>';
 for(const p of d.positions){h+='<div class=c><div class=row><span class=b>'+esc(p.contract)+'</span><span class="b '+cls(p.pl)+'">'+(p.pl>=0?'+':'')+$(p.pl)+' <span class=m>'+pct(p.pl_pct)+'</span></span></div>'+
   '<div class=m>'+esc(p.kind)+(p.qty?' · x'+p.qty:'')+' · in '+(p.entry!=null?p.entry.toFixed(2):'--')+' → now '+(p.mark!=null?(+p.mark).toFixed(2):'--')+(p.dte!=null?' · exp '+esc(p.exp)+' ('+p.dte+'d)':'')+(p.status!='open'?' · '+esc(p.status):'')+'</div>'+
   (p.best!=null?'<div class=m>best '+pct(p.best)+' · worst '+pct(p.worst)+'</div>':'')+
   (p.hits&&p.hits.length?'<div>'+p.hits.map(x=>'<span class="chip hit">+'+x+'%</span>').join('')+'</div>':'')+
   (p.why?'<div class=m>'+esc(p.why)+'</div>':'')+'</div>'}
 h+='<h2>Closed</h2>';
 if(!d.closed.length)h+='<div class="c m">No closed trades yet.</div>';
 for(const t of d.closed){h+='<div class=c><div class=row><span>'+esc(t.contract)+'</span><span class="b '+cls(t.pl)+'">'+(t.pl>=0?'+':'')+$(t.pl)+' <span class=m>'+pct(t.pl_pct)+'</span></span></div><div class=m>'+esc(t.kind)+' · '+esc(t.reason||'')+' · '+esc(t.at)+(t.best!=null?' · best '+pct(t.best):'')+'</div></div>'}
 h+='<h2>Activity</h2><div class=c>'+d.log.map(l=>'<div class=log><span class=m>'+esc(l.at)+'</span> '+esc(l.m)+'</div>').join('')+'</div>';
 h+='<div class=m style="text-align:center;margin-top:12px">Read-only · nothing can be traded from this page</div>';
 document.getElementById('app').innerHTML=h}
load();setInterval(load,20000);document.addEventListener('visibilitychange',()=>{if(!document.hidden)load()});
</script></body></html>"""


def serve(bot, M, port=8765):
    cfg = bot.cfg
    token = cfg.get("dash_token")
    if not token:
        token = secrets.token_urlsafe(9)
        try:
            raw = json.loads(M.CFG_F.read_text()) if M.CFG_F.exists() else {}
            raw["dash_token"] = token
            M.CFG_F.write_text(json.dumps(raw, indent=1))
        except Exception:
            pass

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def send(self, code, body, ctype):
            b = body.encode("utf-8") if isinstance(body, str) else body
            self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

        def do_GET(self):
            u = urlparse(self.path); k = (parse_qs(u.query).get("k") or [""])[0]
            if not secrets.compare_digest(k, token):
                return self.send(403, "forbidden", "text/plain")
            if u.path in ("/", "/index.html"):
                return self.send(200, PAGE.replace("__K__", token), "text/html; charset=utf-8")
            if u.path == "/api/status":
                try:
                    return self.send(200, json.dumps(snapshot(bot, M)), "application/json")
                except Exception as e:
                    return self.send(500, json.dumps({"error": str(e)}), "application/json")
            if u.path == "/manifest.json":
                man = {"name": "Make Me Trade", "short_name": "MMT", "start_url": "/?k=" + token, "display": "standalone",
                       "background_color": "#0b0f17", "theme_color": "#0b0f17"}
                return self.send(200, json.dumps(man), "application/manifest+json")
            return self.send(404, "not found", "text/plain")

        def do_POST(self):
            self.send(405, "read-only", "text/plain")

    try:
        srv = ThreadingHTTPServer(("0.0.0.0", port), H)
    except OSError as e:
        M.say("Phone dashboard not started (port %d busy: %s)" % (port, e), bot.st)
        return None
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = "http://%s:%d/?k=%s" % (lan_ip(), port, token)
    M.say("📱 Phone dashboard: %s  (same Wi-Fi, or your Tailscale name instead of the IP)" % url, bot.st)
    try:
        (M.BASE / "phone_link.txt").write_text(url + "\n")
    except Exception:
        pass
    return srv
