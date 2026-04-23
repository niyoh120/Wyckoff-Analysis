# -*- coding: utf-8 -*-
"""
Wyckoff Dashboard — 本地可视化面板。

stdlib http.server 提供 JSON API + 嵌入式 HTML/CSS/JS SPA。
金融终端风格（Bloomberg 深色主题）。
"""
from __future__ import annotations

import json
import os
import threading
import webbrowser
from functools import partial
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# ---------------------------------------------------------------------------
# Data access layer (thin wrappers over local_db)
# ---------------------------------------------------------------------------

def _get_config() -> dict:
    try:
        from cli.auth import load_config, load_model_configs, load_default_model_id
        cfg = load_config()
        models = load_model_configs()
        default_id = load_default_model_id()
        # mask sensitive keys
        safe = {}
        for k, v in cfg.items():
            sv = str(v or "")
            if any(s in k.lower() for s in ("key", "token", "secret", "password")):
                safe[k] = (sv[:4] + "****" + sv[-4:]) if len(sv) > 8 else ("****" if sv else "")
            else:
                safe[k] = v
        safe_models = []
        for m in models:
            mc = dict(m)
            ak = str(mc.get("api_key", "") or "")
            mc["api_key"] = (ak[:4] + "****" + ak[-4:]) if len(ak) > 8 else ("****" if ak else "")
            safe_models.append(mc)
        return {"config": safe, "models": safe_models, "default_model": default_id}
    except Exception as e:
        return {"config": {}, "models": [], "default_model": "", "error": str(e)}


def _get_memory() -> list[dict]:
    try:
        from integrations.local_db import get_recent_memories
        return get_recent_memories(limit=50)
    except Exception:
        return []


def _delete_memory(mem_id: int) -> bool:
    try:
        from integrations.local_db import get_db
        conn = get_db()
        with conn:
            conn.execute("DELETE FROM agent_memory WHERE id=?", (mem_id,))
        return True
    except Exception:
        return False


def _get_recommendations() -> list[dict]:
    try:
        from integrations.local_db import load_recommendations
        return load_recommendations(limit=100)
    except Exception:
        return []


def _get_signals() -> list[dict]:
    try:
        from integrations.local_db import load_signals
        return load_signals(limit=200)
    except Exception:
        return []


def _get_portfolio() -> dict | None:
    try:
        from integrations.local_db import load_portfolio
        return load_portfolio("USER_LIVE")
    except Exception:
        return None


def _get_sync_status() -> list[dict]:
    try:
        from integrations.local_db import get_sync_meta
        tables = ["recommendation_tracking", "signal_pending", "market_signal_daily", "portfolio"]
        result = []
        for t in tables:
            meta = get_sync_meta(t)
            result.append({"table": t, **(meta or {"row_count": 0, "last_synced_at": None})})
        return result
    except Exception:
        return []


def _get_chat_sessions() -> list[dict]:
    try:
        from integrations.local_db import list_chat_sessions
        return list_chat_sessions(limit=50)
    except Exception:
        return []


def _get_chat_log(session_id: str) -> list[dict]:
    try:
        from integrations.local_db import load_chat_logs
        return load_chat_logs(session_id=session_id)
    except Exception:
        return []


def _get_agent_log_tail(lines: int = 100) -> str:
    try:
        from core.constants import LOCAL_DB_PATH
        log_path = LOCAL_DB_PATH.parent / "agent.log"
        if not log_path.exists():
            return ""
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()
            return "".join(all_lines[-lines:])
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# HTTP Handler
# ---------------------------------------------------------------------------

class _Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):  # noqa: A002
        pass  # silence request logs

    def _json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _html(self, html: str):
        body = html.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path == "/api/config":
            self._json(_get_config())
        elif path == "/api/memory":
            self._json(_get_memory())
        elif path == "/api/recommendations":
            self._json(_get_recommendations())
        elif path == "/api/signals":
            self._json(_get_signals())
        elif path == "/api/portfolio":
            self._json(_get_portfolio() or {})
        elif path == "/api/sync":
            self._json(_get_sync_status())
        elif path == "/api/chat-sessions":
            self._json(_get_chat_sessions())
        elif path.startswith("/api/chat-log/"):
            sid = path.split("/")[-1]
            self._json(_get_chat_log(sid))
        elif path == "/api/agent-log":
            params = parse_qs(parsed.query)
            n = int(params.get("lines", ["100"])[0])
            self._json({"log": _get_agent_log_tail(n)})
        else:
            self._html(_DASHBOARD_HTML)

    def do_DELETE(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        # DELETE /api/memory/123
        if path.startswith("/api/memory/"):
            try:
                mem_id = int(path.split("/")[-1])
                ok = _delete_memory(mem_id)
                self._json({"ok": ok})
            except ValueError:
                self._json({"ok": False, "error": "invalid id"}, 400)
        else:
            self._json({"error": "not found"}, 404)


# ---------------------------------------------------------------------------
# Server start
# ---------------------------------------------------------------------------

def start_dashboard(port: int = 8765):
    """启动 dashboard HTTP 服务并打开浏览器。"""
    from integrations.local_db import init_db
    init_db()

    server = HTTPServer(("127.0.0.1", port), _Handler)
    url = f"http://127.0.0.1:{port}"
    print(f"Wyckoff Dashboard: {url}")
    print("按 Ctrl+C 停止")

    threading.Timer(0.5, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


# ---------------------------------------------------------------------------
# Embedded SPA — Financial Terminal Aesthetic
# ---------------------------------------------------------------------------

_DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Wyckoff Dashboard</title>
<style>
/* ── Reset & Base ── */
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#0a0e17;--bg2:#0f1420;--bg3:#151b2b;
  --border:#1e2740;--border2:#2a3452;
  --text:#c8d1e0;--text2:#8892a8;--text-dim:#505a70;
  --accent:#00d4aa;--accent2:#00b894;
  --red:#ff4757;--amber:#f59e0b;--blue:#3b82f6;
  --green:#10b981;
  --font:'SF Mono','Cascadia Code','Fira Code','JetBrains Mono',Consolas,'Courier New',monospace;
}
html{font-size:13px}
body{
  background:var(--bg);color:var(--text);font-family:var(--font);
  line-height:1.5;overflow:hidden;height:100vh;
}
::selection{background:var(--accent);color:var(--bg)}
::-webkit-scrollbar{width:5px}
::-webkit-scrollbar-track{background:var(--bg2)}
::-webkit-scrollbar-thumb{background:var(--border2);border-radius:3px}

/* ── Layout ── */
.shell{display:flex;height:100vh}
.sidebar{
  width:200px;min-width:200px;background:var(--bg2);
  border-right:1px solid var(--border);display:flex;flex-direction:column;
  padding:16px 0;
}
.logo{
  padding:0 16px 20px;border-bottom:1px solid var(--border);margin-bottom:8px;
  font-size:11px;letter-spacing:2px;text-transform:uppercase;color:var(--accent);
  font-weight:700;
}
.logo span{color:var(--text2);font-weight:400;display:block;font-size:10px;letter-spacing:1px;margin-top:2px}
.nav-item{
  padding:8px 16px;cursor:pointer;font-size:12px;color:var(--text2);
  border-left:2px solid transparent;transition:all .15s;
}
.nav-item:hover{color:var(--text);background:rgba(255,255,255,.02)}
.nav-item.active{color:var(--accent);border-left-color:var(--accent);background:rgba(0,212,170,.04)}
.nav-item .tag{
  display:inline-block;background:var(--bg3);border:1px solid var(--border);
  border-radius:3px;font-size:9px;padding:1px 5px;margin-left:6px;color:var(--text-dim);
}

.main{flex:1;display:flex;flex-direction:column;overflow:hidden}
.topbar{
  height:40px;min-height:40px;border-bottom:1px solid var(--border);
  display:flex;align-items:center;justify-content:space-between;padding:0 20px;
  background:var(--bg2);
}
.topbar-title{font-size:12px;color:var(--text2);letter-spacing:1px;text-transform:uppercase}
.clock{font-size:12px;color:var(--accent);letter-spacing:1px}

.content{flex:1;overflow-y:auto;padding:20px}

/* ── Cards ── */
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:16px;margin-bottom:20px}
.card{
  background:var(--bg2);border:1px solid var(--border);border-radius:4px;
  padding:16px;position:relative;overflow:hidden;
}
.card::before{
  content:'';position:absolute;top:0;left:0;right:0;height:1px;
  background:linear-gradient(90deg,transparent,var(--accent),transparent);opacity:.3;
}
.card-title{
  font-size:10px;letter-spacing:2px;text-transform:uppercase;
  color:var(--text-dim);margin-bottom:12px;
}
.card-value{font-size:24px;font-weight:700;color:var(--accent);line-height:1}
.card-sub{font-size:11px;color:var(--text2);margin-top:6px}

/* ── Table ── */
.tbl{width:100%;border-collapse:collapse;font-size:12px}
.tbl th{
  text-align:left;padding:8px 10px;border-bottom:1px solid var(--border2);
  color:var(--text-dim);font-size:10px;letter-spacing:1px;text-transform:uppercase;
  font-weight:600;position:sticky;top:0;background:var(--bg2);z-index:1;
}
.tbl td{
  padding:7px 10px;border-bottom:1px solid var(--border);color:var(--text);
  white-space:nowrap;
}
.tbl tr:hover td{background:rgba(255,255,255,.015)}
.tbl-wrap{
  background:var(--bg2);border:1px solid var(--border);border-radius:4px;
  overflow:auto;max-height:calc(100vh - 180px);
}
.tbl-wrap::before{
  content:'';display:block;height:1px;
  background:linear-gradient(90deg,transparent,var(--accent),transparent);opacity:.3;
}

/* ── Tags & Pills ── */
.pill{
  display:inline-block;padding:2px 8px;border-radius:3px;font-size:10px;font-weight:600;
  letter-spacing:.5px;
}
.pill-green{background:rgba(16,185,129,.12);color:var(--green);border:1px solid rgba(16,185,129,.2)}
.pill-red{background:rgba(255,71,87,.12);color:var(--red);border:1px solid rgba(255,71,87,.2)}
.pill-amber{background:rgba(245,158,11,.12);color:var(--amber);border:1px solid rgba(245,158,11,.2)}
.pill-blue{background:rgba(59,130,246,.12);color:var(--blue);border:1px solid rgba(59,130,246,.2)}
.pill-dim{background:var(--bg3);color:var(--text-dim);border:1px solid var(--border)}

/* ── Config display ── */
.cfg-row{
  display:flex;justify-content:space-between;align-items:center;
  padding:8px 0;border-bottom:1px solid var(--border);font-size:12px;
}
.cfg-key{color:var(--text2)}
.cfg-val{color:var(--accent);font-weight:600}
.cfg-val.masked{color:var(--text-dim)}

/* ── Memory ── */
.mem-item{
  padding:12px 14px;border-bottom:1px solid var(--border);
  display:flex;justify-content:space-between;align-items:flex-start;gap:12px;
}
.mem-item:last-child{border-bottom:none}
.mem-content{flex:1;font-size:12px;line-height:1.6;white-space:pre-wrap;word-break:break-all}
.mem-meta{font-size:10px;color:var(--text-dim);margin-top:4px}
.btn-del{
  background:none;border:1px solid var(--border);color:var(--red);
  cursor:pointer;font-size:10px;padding:3px 8px;border-radius:3px;
  font-family:var(--font);flex-shrink:0;
}
.btn-del:hover{background:rgba(255,71,87,.1);border-color:var(--red)}

/* ── Sync status ── */
.sync-row{
  display:flex;align-items:center;gap:12px;padding:10px 0;
  border-bottom:1px solid var(--border);font-size:12px;
}
.sync-dot{width:8px;height:8px;border-radius:50%;flex-shrink:0}
.sync-dot.ok{background:var(--green);box-shadow:0 0 6px var(--green)}
.sync-dot.stale{background:var(--amber);box-shadow:0 0 6px var(--amber)}
.sync-dot.none{background:var(--text-dim)}

/* ── Empty state ── */
.empty{text-align:center;padding:40px;color:var(--text-dim);font-size:12px}

/* ── Scanline overlay ── */
body::after{
  content:'';position:fixed;inset:0;pointer-events:none;z-index:9999;
  background:repeating-linear-gradient(0deg,transparent,transparent 2px,rgba(0,0,0,.03) 2px,rgba(0,0,0,.03) 4px);
}

/* ── Animate ── */
@keyframes fadeIn{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
.fade-in{animation:fadeIn .3s ease both}
</style>
</head>
<body>
<div class="shell">
  <!-- Sidebar -->
  <div class="sidebar">
    <div class="logo">WYCKOFF<span>Terminal Dashboard</span></div>
    <div class="nav-item active" data-page="overview">Overview</div>
    <div class="nav-item" data-page="recommendations">Recommendations</div>
    <div class="nav-item" data-page="signals">Signals</div>
    <div class="nav-item" data-page="portfolio">Portfolio</div>
    <div class="nav-item" data-page="memory">Memory</div>
    <div class="nav-item" data-page="config">Config</div>
    <div class="nav-item" data-page="chatlog">Chat Log</div>
    <div class="nav-item" data-page="agentlog">Agent Log</div>
    <div class="nav-item" data-page="sync">Sync Status</div>
  </div>
  <!-- Main -->
  <div class="main">
    <div class="topbar">
      <div class="topbar-title" id="pageTitle">OVERVIEW</div>
      <div class="clock" id="clock"></div>
    </div>
    <div class="content" id="content"></div>
  </div>
</div>

<script>
const $ = s => document.querySelector(s);
const $$ = s => document.querySelectorAll(s);
const API = path => fetch(path).then(r => r.json());

// Clock
function tickClock(){
  const d = new Date();
  const pad = n => String(n).padStart(2,'0');
  $('#clock').textContent = `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}
setInterval(tickClock, 1000);
tickClock();

// Navigation
let currentPage = 'overview';
$$('.nav-item').forEach(el => {
  el.addEventListener('click', () => {
    $$('.nav-item').forEach(n => n.classList.remove('active'));
    el.classList.add('active');
    currentPage = el.dataset.page;
    $('#pageTitle').textContent = currentPage.toUpperCase();
    loadPage(currentPage);
  });
});

// Page renderers
async function loadPage(page) {
  const c = $('#content');
  c.innerHTML = '<div class="empty">Loading...</div>';
  try {
    switch(page) {
      case 'overview': return renderOverview(c);
      case 'recommendations': return renderRecommendations(c);
      case 'signals': return renderSignals(c);
      case 'portfolio': return renderPortfolio(c);
      case 'memory': return renderMemory(c);
      case 'config': return renderConfig(c);
      case 'chatlog': return renderChatLog(c);
      case 'agentlog': return renderAgentLog(c);
      case 'sync': return renderSync(c);
    }
  } catch(e) {
    c.innerHTML = `<div class="empty">Error: ${e.message}</div>`;
  }
}

// ── Overview ──
async function renderOverview(c) {
  const [recs, sigs, port, sync, mem] = await Promise.all([
    API('/api/recommendations'), API('/api/signals'), API('/api/portfolio'),
    API('/api/sync'), API('/api/memory'),
  ]);
  const pendingSigs = Array.isArray(sigs) ? sigs.filter(s => s.status === 'pending').length : 0;
  const totalSigs = Array.isArray(sigs) ? sigs.length : 0;
  const posCount = port?.positions?.length || 0;
  const cash = port?.free_cash || 0;
  const memCount = Array.isArray(mem) ? mem.length : 0;
  const syncOk = Array.isArray(sync) ? sync.filter(s => s.last_synced_at).length : 0;
  const syncTotal = Array.isArray(sync) ? sync.length : 0;

  c.innerHTML = `
    <div class="grid fade-in">
      <div class="card">
        <div class="card-title">AI Recommendations</div>
        <div class="card-value">${Array.isArray(recs) ? recs.length : 0}</div>
        <div class="card-sub">tracked stocks</div>
      </div>
      <div class="card">
        <div class="card-title">Signal Pool</div>
        <div class="card-value">${totalSigs}</div>
        <div class="card-sub">${pendingSigs} pending confirmation</div>
      </div>
      <div class="card">
        <div class="card-title">Portfolio</div>
        <div class="card-value">${posCount}</div>
        <div class="card-sub">positions &middot; cash: &yen;${cash.toLocaleString('zh-CN',{minimumFractionDigits:2})}</div>
      </div>
      <div class="card">
        <div class="card-title">Agent Memory</div>
        <div class="card-value">${memCount}</div>
        <div class="card-sub">stored memories</div>
      </div>
      <div class="card">
        <div class="card-title">Sync Status</div>
        <div class="card-value">${syncOk}/${syncTotal}</div>
        <div class="card-sub">tables synced</div>
      </div>
    </div>
    <div style="margin-top:8px">
      <div class="card fade-in" style="animation-delay:.1s">
        <div class="card-title">Recent Recommendations</div>
        ${renderRecTable(Array.isArray(recs) ? recs.slice(0,8) : [])}
      </div>
    </div>
  `;
}

function renderRecTable(recs) {
  if (!recs.length) return '<div class="empty">No data</div>';
  return `<table class="tbl"><thead><tr>
    <th>Code</th><th>Name</th><th>Camp</th><th>Date</th><th>Init Price</th><th>Cur Price</th><th>AI</th>
  </tr></thead><tbody>${recs.map(r => {
    const code = String(r.code||'').padStart(6,'0');
    const ai = r.is_ai_recommended ? '<span class="pill pill-green">AI</span>' : '<span class="pill pill-dim">Manual</span>';
    return `<tr><td>${code}</td><td>${r.name||''}</td><td>${r.camp||''}</td>
      <td>${r.recommend_date||''}</td><td>${(r.initial_price||0).toFixed(2)}</td>
      <td>${(r.current_price||0).toFixed(2)}</td><td>${ai}</td></tr>`;
  }).join('')}</tbody></table>`;
}

// ── Recommendations ──
async function renderRecommendations(c) {
  const recs = await API('/api/recommendations');
  if (!Array.isArray(recs) || !recs.length) { c.innerHTML = '<div class="empty">No recommendations</div>'; return; }
  c.innerHTML = `<div class="tbl-wrap fade-in">${renderRecTable(recs)}</div>`;
}

// ── Signals ──
async function renderSignals(c) {
  const sigs = await API('/api/signals');
  if (!Array.isArray(sigs) || !sigs.length) { c.innerHTML = '<div class="empty">No signals</div>'; return; }
  const statusPill = s => {
    const m = {pending:'pill-amber',confirmed:'pill-green',expired:'pill-red',rejected:'pill-red'};
    return `<span class="pill ${m[s]||'pill-dim'}">${s}</span>`;
  };
  c.innerHTML = `<div class="tbl-wrap fade-in"><table class="tbl"><thead><tr>
    <th>Code</th><th>Name</th><th>Type</th><th>Status</th><th>Date</th><th>Score</th><th>Days</th><th>Regime</th><th>Industry</th>
  </tr></thead><tbody>${sigs.map(s => {
    const code = String(s.code||'').padStart(6,'0');
    return `<tr><td>${code}</td><td>${s.name||''}</td><td>${s.signal_type||''}</td>
      <td>${statusPill(s.status||'')}</td><td>${s.signal_date||''}</td>
      <td>${(s.signal_score||0).toFixed(2)}</td><td>${s.days_elapsed||0}</td>
      <td>${s.regime||''}</td><td>${s.industry||''}</td></tr>`;
  }).join('')}</tbody></table></div>`;
}

// ── Portfolio ──
async function renderPortfolio(c) {
  const port = await API('/api/portfolio');
  if (!port || !port.portfolio_id) { c.innerHTML = '<div class="empty">No portfolio data</div>'; return; }
  const pos = port.positions || [];
  c.innerHTML = `
    <div class="grid fade-in">
      <div class="card"><div class="card-title">Portfolio ID</div><div style="font-size:14px;color:var(--text)">${port.portfolio_id}</div></div>
      <div class="card"><div class="card-title">Free Cash</div><div class="card-value">&yen;${(port.free_cash||0).toLocaleString('zh-CN',{minimumFractionDigits:2})}</div></div>
      <div class="card"><div class="card-title">Positions</div><div class="card-value">${pos.length}</div></div>
    </div>
    <div class="tbl-wrap fade-in" style="animation-delay:.1s"><table class="tbl"><thead><tr>
      <th>Code</th><th>Name</th><th>Shares</th><th>Cost</th><th>Stop Loss</th>
    </tr></thead><tbody>${pos.map(p => {
      const code = String(p.code||'').padStart(6,'0');
      const sl = p.stop_loss != null ? p.stop_loss.toFixed(2) : '-';
      return `<tr><td>${code}</td><td>${p.name||''}</td><td>${p.shares||0}</td>
        <td>${(p.cost_price||0).toFixed(3)}</td><td>${sl}</td></tr>`;
    }).join('')}</tbody></table></div>`;
}

// ── Memory ──
async function renderMemory(c) {
  const mems = await API('/api/memory');
  if (!Array.isArray(mems) || !mems.length) { c.innerHTML = '<div class="empty">No memories stored</div>'; return; }
  const typePill = t => {
    const m = {session:'pill-blue',fact:'pill-green',preference:'pill-amber'};
    return `<span class="pill ${m[t]||'pill-dim'}">${t}</span>`;
  };
  c.innerHTML = `<div class="tbl-wrap fade-in">${mems.map(m => `
    <div class="mem-item">
      <div style="flex:1">
        <div style="margin-bottom:4px">${typePill(m.memory_type)} ${m.codes ? `<span style="color:var(--text-dim);font-size:10px;margin-left:8px">${m.codes}</span>` : ''}</div>
        <div class="mem-content">${escHtml(m.content)}</div>
        <div class="mem-meta">#${m.id} &middot; ${m.created_at||''}</div>
      </div>
      <button class="btn-del" onclick="delMemory(${m.id})">DEL</button>
    </div>`).join('')}</div>`;
}

function escHtml(s) {
  const d = document.createElement('div');
  d.textContent = s || '';
  return d.innerHTML;
}

window.delMemory = async function(id) {
  if (!confirm('Delete memory #' + id + '?')) return;
  await fetch('/api/memory/' + id, {method:'DELETE'});
  loadPage('memory');
};

// ── Config ──
async function renderConfig(c) {
  const data = await API('/api/config');
  const cfg = data.config || {};
  const models = data.models || [];
  const defId = data.default_model || '';

  let html = '<div class="card fade-in"><div class="card-title">Data Source Config</div>';
  const keys = Object.entries(cfg);
  if (keys.length) {
    keys.forEach(([k,v]) => {
      const isMasked = String(v||'').includes('****');
      html += `<div class="cfg-row"><span class="cfg-key">${k}</span><span class="cfg-val${isMasked?' masked':''}">${v||'<span style="color:var(--text-dim)">not set</span>'}</span></div>`;
    });
  } else {
    html += '<div class="empty">No config</div>';
  }
  html += '</div>';

  html += '<div class="card fade-in" style="margin-top:16px;animation-delay:.1s"><div class="card-title">Model Configs</div>';
  if (models.length) {
    html += '<table class="tbl"><thead><tr><th>ID</th><th>Provider</th><th>Model</th><th>API Key</th><th>Base URL</th><th></th></tr></thead><tbody>';
    models.forEach(m => {
      const isDef = m.id === defId;
      html += `<tr><td>${m.id}${isDef?' <span class="pill pill-green">DEFAULT</span>':''}</td>
        <td>${m.provider_name||''}</td><td>${m.model||''}</td>
        <td class="cfg-val masked">${m.api_key||''}</td>
        <td>${m.base_url||'(default)'}</td><td></td></tr>`;
    });
    html += '</tbody></table>';
  } else {
    html += '<div class="empty">No models configured</div>';
  }
  html += '</div>';
  c.innerHTML = html;
}

// ── Sync ──
async function renderSync(c) {
  const sync = await API('/api/sync');
  if (!Array.isArray(sync) || !sync.length) { c.innerHTML = '<div class="empty">No sync data</div>'; return; }
  const now = Date.now();
  c.innerHTML = `<div class="card fade-in"><div class="card-title">Supabase &rarr; SQLite Sync</div>
    ${sync.map(s => {
      let cls = 'none', label = 'Never synced';
      if (s.last_synced_at) {
        const age = (now - new Date(s.last_synced_at+'Z').getTime()) / 3600000;
        cls = age < 8 ? 'ok' : 'stale';
        label = s.last_synced_at;
      }
      return `<div class="sync-row">
        <div class="sync-dot ${cls}"></div>
        <div style="flex:1;font-weight:600">${s.table}</div>
        <div style="color:var(--text2)">${s.row_count||0} rows</div>
        <div style="color:var(--text-dim);font-size:11px;width:180px;text-align:right">${label}</div>
      </div>`;
    }).join('')}
  </div>`;
}

// ── Chat Log ──
let _chatSessionId = null;
async function renderChatLog(c) {
  if (_chatSessionId) return renderChatSession(c, _chatSessionId);
  const sessions = await API('/api/chat-sessions');
  if (!Array.isArray(sessions) || !sessions.length) { c.innerHTML = '<div class="empty">No chat sessions recorded</div>'; return; }
  c.innerHTML = `<div class="tbl-wrap fade-in"><table class="tbl"><thead><tr>
    <th>Session</th><th>Started</th><th>Ended</th><th>Messages</th><th>Tokens In</th><th>Tokens Out</th><th>Error</th><th></th>
  </tr></thead><tbody>${sessions.map(s => {
    const hasErr = s.last_error ? '<span class="pill pill-red">ERR</span>' : '<span class="pill pill-green">OK</span>';
    return `<tr>
      <td style="color:var(--accent);cursor:pointer" onclick="viewSession('${s.session_id}')">${s.session_id}</td>
      <td>${s.started_at||''}</td><td>${s.ended_at||''}</td>
      <td>${s.msg_count||0}</td><td>${(s.total_tokens_in||0).toLocaleString()}</td>
      <td>${(s.total_tokens_out||0).toLocaleString()}</td><td>${hasErr}</td>
      <td><span style="cursor:pointer;color:var(--accent)" onclick="viewSession('${s.session_id}')">VIEW</span></td>
    </tr>`;
  }).join('')}</tbody></table></div>`;
}

window.viewSession = function(sid) { _chatSessionId = sid; loadPage('chatlog'); };
window.backToSessions = function() { _chatSessionId = null; loadPage('chatlog'); };

async function renderChatSession(c, sid) {
  const logs = await API('/api/chat-log/' + sid);
  if (!Array.isArray(logs) || !logs.length) { c.innerHTML = '<div class="empty">No messages</div>'; return; }
  const rolePill = r => {
    const m = {user:'pill-blue',assistant:'pill-green',error:'pill-red',tool:'pill-dim'};
    return `<span class="pill ${m[r]||'pill-dim'}">${r}</span>`;
  };
  c.innerHTML = `
    <div style="margin-bottom:12px">
      <span style="cursor:pointer;color:var(--accent)" onclick="backToSessions()">&larr; Back to sessions</span>
      <span style="margin-left:12px;color:var(--text-dim)">Session: ${sid}</span>
    </div>
    <div class="tbl-wrap fade-in">${logs.map(l => `
      <div class="mem-item">
        <div style="flex:1">
          <div style="margin-bottom:4px">
            ${rolePill(l.role)}
            <span style="color:var(--text-dim);font-size:10px;margin-left:8px">${l.created_at||''}</span>
            ${l.model ? `<span style="color:var(--text-dim);font-size:10px;margin-left:8px">${l.model}</span>` : ''}
            ${l.tokens_in || l.tokens_out ? `<span style="color:var(--text-dim);font-size:10px;margin-left:8px">↑${l.tokens_in||0} ↓${l.tokens_out||0}</span>` : ''}
            ${l.elapsed_s ? `<span style="color:var(--text-dim);font-size:10px;margin-left:8px">${l.elapsed_s}s</span>` : ''}
          </div>
          ${l.error ? `<div style="color:var(--red);font-size:12px;margin-bottom:4px">${escHtml(l.error)}</div>` : ''}
          <div class="mem-content">${escHtml(l.content)}</div>
          ${l.tool_calls ? `<div style="color:var(--text-dim);font-size:10px;margin-top:4px">tools: ${escHtml(l.tool_calls)}</div>` : ''}
        </div>
      </div>`).join('')}</div>`;
}

// ── Agent Log ──
async function renderAgentLog(c) {
  const data = await API('/api/agent-log?lines=200');
  const log = data?.log || '';
  if (!log) { c.innerHTML = '<div class="empty">No agent log (~/.wyckoff/agent.log)</div>'; return; }
  c.innerHTML = `<div class="card fade-in"><div class="card-title">Agent Log (last 200 lines)</div>
    <pre style="font-size:11px;line-height:1.6;color:var(--text);white-space:pre-wrap;word-break:break-all;max-height:calc(100vh - 160px);overflow-y:auto">${escHtml(log)}</pre>
  </div>`;
}

// Init
loadPage('overview');
</script>
</body>
</html>
"""
