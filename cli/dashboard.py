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
        from cli.auth import load_config, load_model_configs, load_default_model_id, load_fallback_model_id
        cfg = load_config()
        models = load_model_configs()
        default_id = load_default_model_id()
        fallback_id = load_fallback_model_id()
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
        return {"config": safe, "models": safe_models, "default_model": default_id, "fallback_model": fallback_id}
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


def _delete_recommendation(code: str) -> int:
    try:
        from integrations.local_db import delete_recommendations
        return delete_recommendations([code])
    except Exception:
        return 0


def _delete_signal(code: str) -> int:
    try:
        from integrations.local_db import delete_signals
        return delete_signals([code])
    except Exception:
        return 0


def _delete_chat_session(session_id: str) -> int:
    try:
        from integrations.local_db import delete_chat_session
        return delete_chat_session(session_id)
    except Exception:
        return 0


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


def _get_tail_buy() -> list[dict]:
    try:
        from integrations.local_db import load_tail_buy_history
        records = load_tail_buy_history(limit=100)
        if not records:
            from integrations.supabase_tail_buy import load_tail_buy_from_supabase
            records = load_tail_buy_from_supabase(limit=100)
        return records
    except Exception:
        return []


def _delete_tail_buy(code: str, run_date: str) -> int:
    try:
        from integrations.local_db import get_db
        conn = get_db()
        with conn:
            cur = conn.execute(
                "DELETE FROM tail_buy_history WHERE code=? AND run_date=?",
                (code, run_date),
            )
        return cur.rowcount
    except Exception:
        return 0


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


def _get_background_tasks() -> list[dict]:
    try:
        from integrations.local_db import load_background_task_results
        return load_background_task_results(limit=100)
    except Exception:
        return []


def _get_background_task(task_id: str) -> dict:
    try:
        from integrations.local_db import load_background_task_result
        return load_background_task_result(task_id) or {}
    except Exception:
        return {}


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
        elif path == "/api/tail-buy":
            self._json(_get_tail_buy())
        elif path == "/api/portfolio":
            self._json(_get_portfolio() or {})
        elif path == "/api/sync":
            self._json(_get_sync_status())
        elif path == "/api/chat-sessions":
            self._json(_get_chat_sessions())
        elif path.startswith("/api/chat-log/"):
            sid = path.split("/")[-1]
            self._json(_get_chat_log(sid))
        elif path == "/api/background-tasks":
            self._json(_get_background_tasks())
        elif path.startswith("/api/background-tasks/"):
            task_id = path.split("/")[-1]
            self._json(_get_background_task(task_id))
        elif path == "/api/agent-log":
            params = parse_qs(parsed.query)
            n = int(params.get("lines", ["100"])[0])
            self._json({"log": _get_agent_log_tail(n)})
        else:
            self._html(_DASHBOARD_HTML)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length <= 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        if path == "/api/models":
            try:
                body = self._read_body()
                from cli.auth import save_model_entry
                save_model_entry(body)
                self._json({"ok": True})
            except Exception as e:
                self._json({"ok": False, "error": str(e)}, 400)
        else:
            self._json({"error": "not found"}, 404)

    def do_PUT(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        if path.startswith("/api/models/") and path.endswith("/default"):
            model_id = path.split("/")[-2]
            try:
                from cli.auth import set_default_model
                set_default_model(model_id)
                self._json({"ok": True})
            except Exception as e:
                self._json({"ok": False, "error": str(e)}, 400)
        elif path.startswith("/api/models/") and path.endswith("/fallback"):
            model_id = path.split("/")[-2]
            try:
                from cli.auth import set_fallback_model
                set_fallback_model(model_id)
                self._json({"ok": True})
            except Exception as e:
                self._json({"ok": False, "error": str(e)}, 400)
        elif path.startswith("/api/models/"):
            model_id = path.split("/")[-1]
            try:
                body = self._read_body()
                body["id"] = model_id
                if not body.get("api_key"):
                    from cli.auth import load_model_configs
                    for m in load_model_configs():
                        if m["id"] == model_id:
                            body["api_key"] = m["api_key"]
                            break
                from cli.auth import save_model_entry
                save_model_entry(body)
                self._json({"ok": True})
            except Exception as e:
                self._json({"ok": False, "error": str(e)}, 400)
        elif path.startswith("/api/config/"):
            key = path.split("/")[-1]
            try:
                body = self._read_body()
                from cli.auth import save_config_key
                save_config_key(key, body.get("value", ""))
                self._json({"ok": True})
            except Exception as e:
                self._json({"ok": False, "error": str(e)}, 400)
        else:
            self._json({"error": "not found"}, 404)

    def do_DELETE(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        if path.startswith("/api/models/"):
            model_id = path.split("/")[-1]
            try:
                from cli.auth import remove_model_entry
                ok = remove_model_entry(model_id)
                self._json({"ok": ok, "error": "" if ok else "cannot delete last model"})
            except Exception as e:
                self._json({"ok": False, "error": str(e)}, 400)
        elif path.startswith("/api/memory/"):
            try:
                mem_id = int(path.split("/")[-1])
                ok = _delete_memory(mem_id)
                self._json({"ok": ok})
            except ValueError:
                self._json({"ok": False, "error": "invalid id"}, 400)
        elif path.startswith("/api/recommendations/"):
            code = path.split("/")[-1]
            n = _delete_recommendation(code)
            self._json({"ok": n > 0, "deleted": n})
        elif path.startswith("/api/signals/"):
            code = path.split("/")[-1]
            n = _delete_signal(code)
            self._json({"ok": n > 0, "deleted": n})
        elif path.startswith("/api/tail-buy/"):
            parts = path.split("/")
            code, run_date = parts[-2], parts[-1]
            n = _delete_tail_buy(code, run_date)
            self._json({"ok": n > 0, "deleted": n})
        elif path.startswith("/api/chat-sessions/"):
            sid = path.split("/")[-1]
            n = _delete_chat_session(sid)
            self._json({"ok": n > 0, "deleted": n})
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
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#0a0e17;--bg2:#0f1420;--bg3:#151b2b;
  --border:#1e2740;--border2:#2a3452;
  --text:#c8d1e0;--text2:#8892a8;--text-dim:#505a70;
  --accent:#00d4aa;--accent2:#00b894;
  --red:#ff4757;--amber:#f59e0b;--blue:#3b82f6;--green:#10b981;
  --hover-bg:rgba(255,255,255,.02);--hover-td:rgba(255,255,255,.015);
  --scan-a:rgba(0,0,0,.03);
  --font:'SF Mono','Cascadia Code','Fira Code','JetBrains Mono',Consolas,'Courier New',monospace;
}
html.light{
  --bg:#f4f5f7;--bg2:#ffffff;--bg3:#ebedf0;
  --border:#dce0e6;--border2:#c8cdd5;
  --text:#1a1d24;--text2:#5a6270;--text-dim:#9aa0ab;
  --accent:#0a9b7a;--accent2:#088a6b;
  --red:#d63031;--amber:#d4880f;--blue:#2563eb;--green:#059669;
  --hover-bg:rgba(0,0,0,.02);--hover-td:rgba(0,0,0,.02);
  --scan-a:rgba(255,255,255,.04);
}
html{font-size:13px}
body{background:var(--bg);color:var(--text);font-family:var(--font);line-height:1.5;overflow:hidden;height:100vh}
::selection{background:var(--accent);color:var(--bg)}
::-webkit-scrollbar{width:5px}
::-webkit-scrollbar-track{background:var(--bg2)}
::-webkit-scrollbar-thumb{background:var(--border2);border-radius:3px}

.shell{display:flex;height:100vh}
.sidebar{width:200px;min-width:200px;background:var(--bg2);border-right:1px solid var(--border);display:flex;flex-direction:column;padding:16px 0}
.logo{padding:0 16px 20px;border-bottom:1px solid var(--border);margin-bottom:8px;font-size:11px;letter-spacing:2px;text-transform:uppercase;color:var(--accent);font-weight:700}
.logo span{color:var(--text2);font-weight:400;display:block;font-size:10px;letter-spacing:1px;margin-top:2px}
.nav-item{padding:8px 16px;cursor:pointer;font-size:12px;color:var(--text2);border-left:2px solid transparent;transition:all .15s}
.nav-item:hover{color:var(--text);background:var(--hover-bg)}
.nav-item.active{color:var(--accent);border-left-color:var(--accent);background:rgba(0,212,170,.04)}
.main{flex:1;display:flex;flex-direction:column;overflow:hidden}
.topbar{height:40px;min-height:40px;border-bottom:1px solid var(--border);display:flex;align-items:center;justify-content:space-between;padding:0 20px;background:var(--bg2)}
.topbar-title{font-size:12px;color:var(--text2);letter-spacing:1px;text-transform:uppercase}
.topbar-r{display:flex;align-items:center;gap:12px}
.clock{font-size:12px;color:var(--accent);letter-spacing:1px}
.tb-btn{background:none;border:1px solid var(--border);color:var(--text2);cursor:pointer;font-size:11px;padding:3px 8px;border-radius:3px;font-family:var(--font);transition:all .15s}
.tb-btn:hover{color:var(--accent);border-color:var(--accent)}
.content{flex:1;overflow-y:auto;padding:20px}

.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:16px;margin-bottom:20px}
.card{background:var(--bg2);border:1px solid var(--border);border-radius:4px;padding:16px;position:relative;overflow:hidden}
.card::before{content:'';position:absolute;top:0;left:0;right:0;height:1px;background:linear-gradient(90deg,transparent,var(--accent),transparent);opacity:.3}
.card-title{font-size:10px;letter-spacing:2px;text-transform:uppercase;color:var(--text-dim);margin-bottom:12px}
.card-value{font-size:24px;font-weight:700;color:var(--accent);line-height:1}
.card-sub{font-size:11px;color:var(--text2);margin-top:6px}

.tbl{width:100%;border-collapse:collapse;font-size:12px}
.tbl th{text-align:left;padding:8px 10px;border-bottom:1px solid var(--border2);color:var(--text-dim);font-size:10px;letter-spacing:1px;text-transform:uppercase;font-weight:600;position:sticky;top:0;background:var(--bg2);z-index:1}
.tbl td{padding:7px 10px;border-bottom:1px solid var(--border);color:var(--text);white-space:nowrap}
.tbl tr:hover td{background:var(--hover-td)}
.tbl-wrap{background:var(--bg2);border:1px solid var(--border);border-radius:4px;overflow:auto;max-height:calc(100vh - 180px)}
.tbl-wrap::before{content:'';display:block;height:1px;background:linear-gradient(90deg,transparent,var(--accent),transparent);opacity:.3}

.pill{display:inline-block;padding:2px 8px;border-radius:3px;font-size:10px;font-weight:600;letter-spacing:.5px}
.pill-green{background:rgba(16,185,129,.12);color:var(--green);border:1px solid rgba(16,185,129,.2)}
.pill-red{background:rgba(255,71,87,.12);color:var(--red);border:1px solid rgba(255,71,87,.2)}
.pill-amber{background:rgba(245,158,11,.12);color:var(--amber);border:1px solid rgba(245,158,11,.2)}
.pill-yellow{background:rgba(234,179,8,.12);color:#eab308;border:1px solid rgba(234,179,8,.25)}
.pill-blue{background:rgba(59,130,246,.12);color:var(--blue);border:1px solid rgba(59,130,246,.2)}
.pill-dim{background:var(--bg3);color:var(--text-dim);border:1px solid var(--border)}

.cfg-row{display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:1px solid var(--border);font-size:12px}
.cfg-key{color:var(--text2)}.cfg-val{color:var(--accent);font-weight:600}.cfg-val.masked{color:var(--text-dim)}
.mem-item{padding:12px 14px;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:flex-start;gap:12px}
.mem-item:last-child{border-bottom:none}
.mem-content{flex:1;font-size:12px;line-height:1.6;white-space:pre-wrap;word-break:break-all}
.mem-meta{font-size:10px;color:var(--text-dim);margin-top:4px}
.btn-del{background:none;border:1px solid var(--border);color:var(--red);cursor:pointer;font-size:10px;padding:3px 8px;border-radius:3px;font-family:var(--font);flex-shrink:0}
.btn-del:hover{background:rgba(255,71,87,.1);border-color:var(--red)}
.sync-row{display:flex;align-items:center;gap:12px;padding:10px 0;border-bottom:1px solid var(--border);font-size:12px}
.sync-dot{width:8px;height:8px;border-radius:50%;flex-shrink:0}
.sync-dot.ok{background:var(--green);box-shadow:0 0 6px var(--green)}
.sync-dot.stale{background:var(--amber);box-shadow:0 0 6px var(--amber)}
.sync-dot.none{background:var(--text-dim)}
.empty{text-align:center;padding:40px;color:var(--text-dim);font-size:12px}
.btn-accent{background:rgba(0,212,170,.1);border:1px solid var(--accent);color:var(--accent);cursor:pointer;font-size:11px;padding:4px 12px;border-radius:3px;font-family:var(--font);transition:all .15s}
.btn-accent:hover{background:rgba(0,212,170,.2)}
.btn-edit{background:none;border:1px solid var(--border);color:var(--blue);cursor:pointer;font-size:10px;padding:3px 8px;border-radius:3px;font-family:var(--font);margin-right:4px}
.btn-edit:hover{background:rgba(59,130,246,.1);border-color:var(--blue)}
.btn-default{background:none;border:1px solid var(--border);color:var(--amber);cursor:pointer;font-size:10px;padding:3px 8px;border-radius:3px;font-family:var(--font);margin-right:4px}
.btn-default:hover{background:rgba(245,158,11,.1);border-color:var(--amber)}
.model-form{background:var(--bg3);border:1px solid var(--border2);border-radius:4px;padding:16px;margin-top:12px}
.form-row{display:flex;align-items:center;margin-bottom:10px;gap:8px}
.form-row:last-child{margin-bottom:0}
.form-label{width:80px;font-size:11px;color:var(--text2);text-align:right;flex-shrink:0}
.form-input{flex:1;background:var(--bg);border:1px solid var(--border);color:var(--text);padding:6px 10px;border-radius:3px;font-family:var(--font);font-size:12px;outline:none}
.form-input:focus{border-color:var(--accent)}
.form-select{flex:1;background:var(--bg);border:1px solid var(--border);color:var(--text);padding:6px 10px;border-radius:3px;font-family:var(--font);font-size:12px;outline:none;-webkit-appearance:none}
.form-select:focus{border-color:var(--accent)}
.form-select option{background:var(--bg);color:var(--text)}
.form-actions{display:flex;gap:8px;margin-top:12px;justify-content:flex-end}
body::after{content:'';position:fixed;inset:0;pointer-events:none;z-index:9999;background:repeating-linear-gradient(0deg,transparent,transparent 2px,var(--scan-a) 2px,var(--scan-a) 4px)}
@keyframes fadeIn{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
.fade-in{animation:fadeIn .3s ease both}
</style>
</head>
<body>
<div class="shell">
  <div class="sidebar">
    <div class="logo">WYCKOFF<span>Terminal Dashboard</span></div>
    <div class="nav-item active" data-page="overview" data-i18n="nav_overview"></div>
    <div class="nav-item" data-page="recommendations" data-i18n="nav_recommendations"></div>
    <div class="nav-item" data-page="signals" data-i18n="nav_signals"></div>
    <div class="nav-item" data-page="tailbuy" data-i18n="nav_tailbuy"></div>
    <div class="nav-item" data-page="portfolio" data-i18n="nav_portfolio"></div>
    <div class="nav-item" data-page="memory" data-i18n="nav_memory"></div>
    <div class="nav-item" data-page="config" data-i18n="nav_config"></div>
    <div class="nav-item" data-page="bgtasks" data-i18n="nav_bgtasks"></div>
    <div class="nav-item" data-page="chatlog" data-i18n="nav_chatlog"></div>
    <div class="nav-item" data-page="agentlog" data-i18n="nav_agentlog"></div>
    <div class="nav-item" data-page="sync" data-i18n="nav_sync"></div>
  </div>
  <div class="main">
    <div class="topbar">
      <div class="topbar-title" id="pageTitle"></div>
      <div class="topbar-r">
        <button class="tb-btn" id="btnTheme" onclick="toggleTheme()"></button>
        <button class="tb-btn" id="btnLang" onclick="toggleLang()"></button>
        <div class="clock" id="clock"></div>
      </div>
    </div>
    <div class="content" id="content"></div>
  </div>
</div>
<script>
const $=s=>document.querySelector(s),$$=s=>document.querySelectorAll(s);
const API=p=>fetch(p).then(r=>r.json());

// ═══ i18n ═══
const I18N={
zh:{
  nav_overview:'总览',nav_recommendations:'AI 推荐',nav_signals:'信号池',nav_tailbuy:'尾盘记录',nav_portfolio:'持仓',
  nav_memory:'Agent 记忆',nav_config:'配置',nav_bgtasks:'后台任务',nav_chatlog:'对话日志',nav_agentlog:'Agent 日志',nav_sync:'同步状态',
  theme_dark:'深色',theme_light:'浅色',
  overview:'总览',recommendations:'AI 推荐',signals:'信号池',tailbuy:'尾盘记录',portfolio:'持仓',
  memory:'Agent 记忆',config:'配置',bgtasks:'后台任务',chatlog:'对话日志',agentlog:'Agent 日志',sync:'同步状态',
  no_tailbuy:'暂无尾盘买入记录',th_run_date:'执行日',th_signal_type:'信号',th_rule_score:'规则分',th_priority:'优先级',th_llm:'LLM',confirm_del_tailbuy:'确认删除尾盘记录：',
  card_recs:'AI 推荐跟踪',card_signals:'信号确认池',card_portfolio:'持仓',card_memory:'Agent 记忆',card_sync:'同步状态',
  tracked:'只跟踪中',pending_confirm:'条待确认',positions:'持仓',cash:'可用资金',stored:'条记忆',synced:'表已同步',
  recent_recs:'最近推荐',no_data:'暂无数据',loading:'加载中...',
  th_code:'代码',th_name:'名称',th_camp:'阵营',th_date:'日期',th_init_price:'推荐价',th_cur_price:'现价',th_ai:'来源',
  th_type:'类型',th_status:'状态',th_score:'评分',th_days:'天数',th_regime:'市况',th_industry:'行业',
  th_shares:'股数',th_cost:'成本',th_stop_loss:'止损',
  portfolio_id:'组合 ID',free_cash:'可用资金',no_portfolio:'暂无持仓数据',
  no_memory:'暂无记忆',del:'删除',confirm_del:'确认删除记忆 #',
  ds_config:'数据源配置',model_config:'模型配置',not_set:'未配置',no_config:'暂无配置',no_models:'暂无模型',
  add_model:'添加模型',edit:'编辑',save:'保存',cancel:'取消',set_default:'设为默认',confirm_del_model:'确认删除模型：',
  model_alias:'别名',provider:'供应商',api_key_label:'API Key',model_name:'模型名',base_url_label:'Base URL',
  th_id:'ID',th_provider:'供应商',th_model:'模型',th_apikey:'API Key',th_baseurl:'Base URL',th_actions:'操作',
  sync_title:'Supabase → SQLite 同步',never_synced:'从未同步',rows:'行',
  no_bg_tasks:'暂无后台任务',th_task:'任务',th_tool:'工具',bg_session:'会话',th_created:'时间',th_summary:'摘要',view_result:'查看结果',bg_back:'返回',
  no_sessions:'暂无对话记录',th_session:'会话',th_started:'开始',th_ended:'结束',
  th_messages:'消息数',th_tokens_in:'输入 Token',th_tokens_out:'输出 Token',th_error:'状态',
  view:'查看',back:'返回列表',session:'会话',no_messages:'暂无消息',
  agent_log_title:'Agent 日志（最近 200 行）',no_agent_log:'暂无日志 (~/.wyckoff/agent.log)',
  no_recs:'暂无推荐',no_signals:'暂无信号',
  confirm_del_rec:'确认删除推荐记录：',confirm_del_sig:'确认删除信号记录：',confirm_del_session:'确认删除整个会话？会话 ID：',
},
en:{
  nav_overview:'Overview',nav_recommendations:'Recommendations',nav_signals:'Signals',nav_tailbuy:'Tail Buy',nav_portfolio:'Portfolio',
  nav_memory:'Memory',nav_config:'Config',nav_bgtasks:'Background Tasks',nav_chatlog:'Chat Log',nav_agentlog:'Agent Log',nav_sync:'Sync Status',
  theme_dark:'Dark',theme_light:'Light',
  overview:'Overview',recommendations:'Recommendations',signals:'Signals',tailbuy:'Tail Buy',portfolio:'Portfolio',
  memory:'Memory',config:'Config',bgtasks:'Background Tasks',chatlog:'Chat Log',agentlog:'Agent Log',sync:'Sync Status',
  no_tailbuy:'No tail buy records',th_run_date:'Run Date',th_signal_type:'Signal',th_rule_score:'Rule Score',th_priority:'Priority',th_llm:'LLM',confirm_del_tailbuy:'Delete tail buy record: ',
  card_recs:'AI Recommendations',card_signals:'Signal Pool',card_portfolio:'Portfolio',card_memory:'Agent Memory',card_sync:'Sync Status',
  tracked:'tracked stocks',pending_confirm:'pending confirmation',positions:'positions',cash:'cash',stored:'stored memories',synced:'tables synced',
  recent_recs:'Recent Recommendations',no_data:'No data',loading:'Loading...',
  th_code:'Code',th_name:'Name',th_camp:'Camp',th_date:'Date',th_init_price:'Init Price',th_cur_price:'Cur Price',th_ai:'Source',
  th_type:'Type',th_status:'Status',th_score:'Score',th_days:'Days',th_regime:'Regime',th_industry:'Industry',
  th_shares:'Shares',th_cost:'Cost',th_stop_loss:'Stop Loss',
  portfolio_id:'Portfolio ID',free_cash:'Free Cash',no_portfolio:'No portfolio data',
  no_memory:'No memories stored',del:'DEL',confirm_del:'Delete memory #',
  ds_config:'Data Source Config',model_config:'Model Configs',not_set:'not set',no_config:'No config',no_models:'No models configured',
  add_model:'Add Model',edit:'Edit',save:'Save',cancel:'Cancel',set_default:'Set Default',confirm_del_model:'Delete model: ',
  model_alias:'Alias',provider:'Provider',api_key_label:'API Key',model_name:'Model',base_url_label:'Base URL',
  th_id:'ID',th_provider:'Provider',th_model:'Model',th_apikey:'API Key',th_baseurl:'Base URL',th_actions:'Actions',
  sync_title:'Supabase → SQLite Sync',never_synced:'Never synced',rows:'rows',
  no_bg_tasks:'No background tasks',th_task:'Task',th_tool:'Tool',bg_session:'Session',th_created:'Time',th_summary:'Summary',view_result:'View',bg_back:'Back',
  no_sessions:'No chat sessions recorded',th_session:'Session',th_started:'Started',th_ended:'Ended',
  th_messages:'Messages',th_tokens_in:'Tokens In',th_tokens_out:'Tokens Out',th_error:'Status',
  view:'VIEW',back:'Back to sessions',session:'Session',no_messages:'No messages',
  agent_log_title:'Agent Log (last 200 lines)',no_agent_log:'No agent log (~/.wyckoff/agent.log)',
  no_recs:'No recommendations',no_signals:'No signals',
  confirm_del_rec:'Delete recommendation: ',confirm_del_sig:'Delete signal: ',confirm_del_session:'Delete entire session? ID: ',
}};
let _lang = localStorage.getItem('wk_lang') || 'zh';
function t(k){return (I18N[_lang]||I18N.zh)[k]||k}
function applyI18n(){
  $$('[data-i18n]').forEach(el=>{el.textContent=t(el.dataset.i18n)});
  $('#btnLang').textContent=_lang==='zh'?'EN':'中';
  $('#btnTheme').textContent=document.documentElement.classList.contains('light')?t('theme_dark'):t('theme_light');
  $('#pageTitle').textContent=t(currentPage);
}
function toggleLang(){_lang=_lang==='zh'?'en':'zh';localStorage.setItem('wk_lang',_lang);applyI18n();loadPage(currentPage)}

// ═══ Theme ═══
let _theme=localStorage.getItem('wk_theme')||'dark';
function applyTheme(){
  document.documentElement.classList.toggle('light',_theme==='light');
  $('#btnTheme').textContent=_theme==='light'?t('theme_dark'):t('theme_light');
}
function toggleTheme(){_theme=_theme==='dark'?'light':'dark';localStorage.setItem('wk_theme',_theme);applyTheme()}
applyTheme();

// ═══ Clock & Timezone ═══
function tickClock(){const d=new Date(),p=n=>String(n).padStart(2,'0');$('#clock').textContent=`${d.getFullYear()}-${p(d.getMonth()+1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`}
setInterval(tickClock,1000);tickClock();
function localTime(s){if(!s)return '';try{const d=new Date(s.includes('T')||s.includes('Z')?s:s.replace(' ','T')+'Z');if(isNaN(d))return s;const p=n=>String(n).padStart(2,'0');return `${d.getFullYear()}-${p(d.getMonth()+1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`}catch(e){return s}}

// ═══ Nav ═══
let currentPage='overview';
$$('.nav-item').forEach(el=>{el.addEventListener('click',()=>{
  $$('.nav-item').forEach(n=>n.classList.remove('active'));el.classList.add('active');
  currentPage=el.dataset.page;$('#pageTitle').textContent=t(currentPage);loadPage(currentPage);
})});

async function loadPage(page){
  const c=$('#content');c.innerHTML=`<div class="empty">${t('loading')}</div>`;
  try{
    switch(page){
      case 'overview':return renderOverview(c);case 'recommendations':return renderRecommendations(c);
      case 'signals':return renderSignals(c);case 'tailbuy':return renderTailBuy(c);case 'portfolio':return renderPortfolio(c);
      case 'memory':return renderMemory(c);case 'config':return renderConfig(c);
      case 'bgtasks':return renderBgTasks(c);
      case 'chatlog':return renderChatLog(c);case 'agentlog':return renderAgentLog(c);
      case 'sync':return renderSync(c);
    }
  }catch(e){c.innerHTML=`<div class="empty">Error: ${e.message}</div>`}
}

function escHtml(s){const d=document.createElement('div');d.textContent=s||'';return d.innerHTML}

// ═══ Overview ═══
async function renderOverview(c){
  const [recs,sigs,port,sync,mem]=await Promise.all([API('/api/recommendations'),API('/api/signals'),API('/api/portfolio'),API('/api/sync'),API('/api/memory')]);
  const pendingSigs=Array.isArray(sigs)?sigs.filter(s=>s.status==='pending').length:0;
  const totalSigs=Array.isArray(sigs)?sigs.length:0;
  const posCount=port?.positions?.length||0;const cash=port?.free_cash||0;
  const memCount=Array.isArray(mem)?mem.length:0;
  const syncOk=Array.isArray(sync)?sync.filter(s=>s.last_synced_at).length:0;
  const syncTotal=Array.isArray(sync)?sync.length:0;
  c.innerHTML=`
    <div class="grid fade-in">
      <div class="card"><div class="card-title">${t('card_recs')}</div><div class="card-value">${Array.isArray(recs)?recs.length:0}</div><div class="card-sub">${t('tracked')}</div></div>
      <div class="card"><div class="card-title">${t('card_signals')}</div><div class="card-value">${totalSigs}</div><div class="card-sub">${pendingSigs} ${t('pending_confirm')}</div></div>
      <div class="card"><div class="card-title">${t('card_portfolio')}</div><div class="card-value">${posCount}</div><div class="card-sub">${t('positions')} · ${t('cash')}: &yen;${cash.toLocaleString('zh-CN',{minimumFractionDigits:2})}</div></div>
      <div class="card"><div class="card-title">${t('card_memory')}</div><div class="card-value">${memCount}</div><div class="card-sub">${t('stored')}</div></div>
      <div class="card"><div class="card-title">${t('card_sync')}</div><div class="card-value">${syncOk}/${syncTotal}</div><div class="card-sub">${t('synced')}</div></div>
    </div>
    <div style="margin-top:8px"><div class="card fade-in" style="animation-delay:.1s"><div class="card-title">${t('recent_recs')}</div>${renderRecTable(Array.isArray(recs)?recs.slice(0,8):[],false)}</div></div>`;
}
function renderRecTable(recs,showDel){
  if(!recs.length)return `<div class="empty">${t('no_data')}</div>`;
  return `<table class="tbl"><thead><tr><th>${t('th_code')}</th><th>${t('th_name')}</th><th>${t('th_camp')}</th><th>${t('th_date')}</th><th>${t('th_init_price')}</th><th>${t('th_cur_price')}</th><th>${t('th_ai')}</th>${showDel?'<th></th>':''}</tr></thead><tbody>${recs.map(r=>{
    const code=String(r.code||'').padStart(6,'0');
    const ai=r.is_ai_recommended?'<span class="pill pill-green">AI</span>':'<span class="pill pill-dim">Manual</span>';
    return `<tr><td>${code}</td><td>${r.name||''}</td><td>${r.camp||''}</td><td>${localTime(r.recommend_date)}</td><td>${(r.initial_price||0).toFixed(2)}</td><td>${(r.current_price||0).toFixed(2)}</td><td>${ai}</td>${showDel?`<td><button class="btn-del" onclick="delRec('${code}')">${t('del')}</button></td>`:''}</tr>`}).join('')}</tbody></table>`}

// ═══ Recommendations ═══
async function renderRecommendations(c){
  const recs=await API('/api/recommendations');
  if(!Array.isArray(recs)||!recs.length){c.innerHTML=`<div class="empty">${t('no_recs')}</div>`;return}
  c.innerHTML=`<div class="tbl-wrap fade-in">${renderRecTable(recs,true)}</div>`}
window.delRec=async function(code){if(!confirm(t('confirm_del_rec')+code+'?'))return;await fetch('/api/recommendations/'+code,{method:'DELETE'});loadPage('recommendations')};

// ═══ Signals ═══
async function renderSignals(c){
  const sigs=await API('/api/signals');
  if(!Array.isArray(sigs)||!sigs.length){c.innerHTML=`<div class="empty">${t('no_signals')}</div>`;return}
  const statusPill=s=>{const m={pending:'pill-amber',confirmed:'pill-green',expired:'pill-red',rejected:'pill-red'};return `<span class="pill ${m[s]||'pill-dim'}">${s}</span>`};
  c.innerHTML=`<div class="tbl-wrap fade-in"><table class="tbl"><thead><tr><th>${t('th_code')}</th><th>${t('th_name')}</th><th>${t('th_type')}</th><th>${t('th_status')}</th><th>${t('th_date')}</th><th>${t('th_score')}</th><th>${t('th_days')}</th><th>${t('th_regime')}</th><th>${t('th_industry')}</th><th></th></tr></thead><tbody>${sigs.map(s=>{
    const code=String(s.code||'').padStart(6,'0');
    return `<tr><td>${code}</td><td>${s.name||''}</td><td>${s.signal_type||''}</td><td>${statusPill(s.status||'')}</td><td>${localTime(s.signal_date)}</td><td>${(s.signal_score||0).toFixed(2)}</td><td>${s.days_elapsed||0}</td><td>${s.regime||''}</td><td>${s.industry||''}</td><td><button class="btn-del" onclick="delSig('${code}')">${t('del')}</button></td></tr>`}).join('')}</tbody></table></div>`}
window.delSig=async function(code){if(!confirm(t('confirm_del_sig')+code+'?'))return;await fetch('/api/signals/'+code,{method:'DELETE'});loadPage('signals')};

// ═══ Tail Buy ═══
async function renderTailBuy(c){
  const rows=await API('/api/tail-buy');
  if(!Array.isArray(rows)||!rows.length){c.innerHTML=`<div class="empty">${t('no_tailbuy')}</div>`;return}
  const llmPill=d=>{const m={BUY:'pill-green',WATCH:'pill-amber',SKIP:'pill-red'};return d?`<span class="pill ${m[d]||'pill-dim'}">${d}</span>`:'<span class="pill pill-dim">-</span>'};
  c.innerHTML=`<div class="tbl-wrap fade-in"><table class="tbl"><thead><tr><th>${t('th_code')}</th><th>${t('th_name')}</th><th>${t('th_run_date')}</th><th>${t('th_signal_type')}</th><th>${t('th_rule_score')}</th><th>${t('th_priority')}</th><th>${t('th_llm')}</th><th></th></tr></thead><tbody>${rows.map(r=>{
    const code=String(r.code||'').padStart(6,'0');
    return `<tr><td>${code}</td><td>${r.name||''}</td><td>${localTime(r.run_date)}</td><td>${r.signal_type||''}</td><td>${(r.rule_score||0).toFixed(1)}</td><td>${(r.priority_score||0).toFixed(1)}</td><td>${llmPill(r.llm_decision)}</td><td><button class="btn-del" onclick="delTailBuy('${code}','${r.run_date||''}')">${t('del')}</button></td></tr>`}).join('')}</tbody></table></div>`}
window.delTailBuy=async function(code,rd){if(!confirm(t('confirm_del_tailbuy')+code+'?'))return;await fetch('/api/tail-buy/'+code+'/'+rd,{method:'DELETE'});loadPage('tailbuy')};

// ═══ Portfolio ═══
async function renderPortfolio(c){
  const port=await API('/api/portfolio');
  if(!port||!port.portfolio_id){c.innerHTML=`<div class="empty">${t('no_portfolio')}</div>`;return}
  const pos=port.positions||[];
  c.innerHTML=`
    <div class="grid fade-in">
      <div class="card"><div class="card-title">${t('portfolio_id')}</div><div style="font-size:14px;color:var(--text)">${port.portfolio_id}</div></div>
      <div class="card"><div class="card-title">${t('free_cash')}</div><div class="card-value">&yen;${(port.free_cash||0).toLocaleString('zh-CN',{minimumFractionDigits:2})}</div></div>
      <div class="card"><div class="card-title">${t('positions')}</div><div class="card-value">${pos.length}</div></div>
    </div>
    <div class="tbl-wrap fade-in" style="animation-delay:.1s"><table class="tbl"><thead><tr><th>${t('th_code')}</th><th>${t('th_name')}</th><th>${t('th_shares')}</th><th>${t('th_cost')}</th><th>${t('th_stop_loss')}</th></tr></thead><tbody>${pos.map(p=>{
      const code=String(p.code||'').padStart(6,'0');const sl=p.stop_loss!=null?p.stop_loss.toFixed(2):'-';
      return `<tr><td>${code}</td><td>${p.name||''}</td><td>${p.shares||0}</td><td>${(p.cost_price||0).toFixed(3)}</td><td>${sl}</td></tr>`}).join('')}</tbody></table></div>`}

// ═══ Memory ═══
async function renderMemory(c){
  const mems=await API('/api/memory');
  if(!Array.isArray(mems)||!mems.length){c.innerHTML=`<div class="empty">${t('no_memory')}</div>`;return}
  const typePill=tp=>{const m={session:'pill-blue',fact:'pill-green',preference:'pill-amber'};return `<span class="pill ${m[tp]||'pill-dim'}">${tp}</span>`};
  c.innerHTML=`<div class="tbl-wrap fade-in">${mems.map(m=>`
    <div class="mem-item"><div style="flex:1">
      <div style="margin-bottom:4px">${typePill(m.memory_type)} ${m.codes?`<span style="color:var(--text-dim);font-size:10px;margin-left:8px">${m.codes}</span>`:''}</div>
      <div class="mem-content">${escHtml(m.content)}</div>
      <div class="mem-meta">#${m.id} · ${localTime(m.created_at)}</div>
    </div><button class="btn-del" onclick="delMemory(${m.id})">${t('del')}</button></div>`).join('')}</div>`}
window.delMemory=async function(id){if(!confirm(t('confirm_del')+id+'?'))return;await fetch('/api/memory/'+id,{method:'DELETE'});loadPage('memory')};

// ═══ Config ═══
let _editingModel=null;
const _defaultModels={gemini:'gemini-2.5-flash',openai:'gpt-4o',claude:'claude-sonnet-4-20250514'};

function _modelForm(m,isNew){
  const id=m?.id||'';const prov=m?.provider_name||'gemini';const model=m?.model||'';const url=m?.base_url||'';
  return `<div class="model-form" id="model-form">
    <div class="form-row"><span class="form-label">${t('model_alias')}</span><input class="form-input" id="mf-id" value="${escHtml(id)}" ${isNew?'':'readonly style="opacity:.6;cursor:not-allowed"'} placeholder="e.g. gemini, longcat"></div>
    <div class="form-row"><span class="form-label">${t('provider')}</span><select class="form-select" id="mf-provider">
      <option value="gemini" ${prov==='gemini'?'selected':''}>Gemini (Google)</option>
      <option value="openai" ${prov==='openai'?'selected':''}>OpenAI / Compatible</option>
      <option value="claude" ${prov==='claude'?'selected':''}>Claude (Anthropic)</option>
    </select></div>
    <div class="form-row"><span class="form-label">${t('api_key_label')}</span><input class="form-input" id="mf-key" type="password" value="" placeholder="${isNew?'':'(unchanged) enter new key to update'}"></div>
    <div class="form-row"><span class="form-label">${t('model_name')}</span><input class="form-input" id="mf-model" value="${escHtml(model)}" placeholder="${_defaultModels[prov]||''}"></div>
    <div class="form-row"><span class="form-label">${t('base_url_label')}</span><input class="form-input" id="mf-url" value="${escHtml(url)}" placeholder="(optional)"></div>
    <div class="form-actions">
      <button class="btn-del" onclick="_cancelModelForm()">${t('cancel')}</button>
      <button class="btn-accent" onclick="_saveModel(${isNew})">${t('save')}</button>
    </div></div>`}

async function renderConfig(c){
  const data=await API('/api/config');const cfg=data.config||{};const models=data.models||[];const defId=data.default_model||'';const fbId=data.fallback_model||'';
  // --- data source config ---
  const editableKeys=['tushare_token','tickflow_api_key'];
  let html=`<div class="card fade-in"><div class="card-title">${t('ds_config')}</div>`;
  const keys=Object.entries(cfg).filter(([k])=>k!=='models'&&k!=='default');
  if(keys.length){keys.forEach(([k,v])=>{
    const isMasked=String(v||'').includes('****');
    const canEdit=editableKeys.includes(k);
    html+=`<div class="cfg-row"><span class="cfg-key">${k}</span><span class="cfg-val${isMasked?' masked':''}" id="ds-val-${k}">${v||`<span style="color:var(--text-dim)">${t('not_set')}</span>`}</span>`;
    if(canEdit)html+=`<button class="btn-edit" onclick="_editDsKey('${k}')">${t('edit')}</button>`;
    html+=`</div>`})}
  else{html+=`<div class="empty">${t('no_config')}</div>`}
  html+='</div>';
  // --- model config ---
  html+=`<div class="card fade-in" style="margin-top:16px;animation-delay:.1s"><div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px"><div class="card-title" style="margin-bottom:0">${t('model_config')}</div><button class="btn-accent" onclick="_addModel()">${t('add_model')}</button></div>`;
  if(models.length){
    html+=`<table class="tbl"><thead><tr><th>${t('th_id')}</th><th>${t('th_provider')}</th><th>${t('th_model')}</th><th>${t('th_apikey')}</th><th>${t('th_baseurl')}</th><th>${t('th_actions')}</th></tr></thead><tbody>`;
    models.forEach(m=>{const isDef=m.id===defId;const isFb=m.id===fbId;
      html+=`<tr><td>${escHtml(m.id)}${isDef?' <span class="pill pill-green">DEFAULT</span>':''}${isFb?' <span class="pill pill-yellow">FALLBACK</span>':''}</td><td>${escHtml(m.provider_name||'')}</td><td>${escHtml(m.model||'')}</td><td class="cfg-val masked">${m.api_key||''}</td><td>${escHtml(m.base_url||'(default)')}</td><td style="white-space:nowrap">`;
      html+=`<button class="btn-edit" onclick="_editModel('${escHtml(m.id)}')">${t('edit')}</button>`;
      if(!isDef)html+=`<button class="btn-default" onclick="_setDefault('${escHtml(m.id)}')">${t('set_default')}</button>`;
      if(!isFb&&!isDef)html+=`<button class="btn-default" onclick="_setFallback('${escHtml(m.id)}')">⚡Fallback</button>`;
      html+=`<button class="btn-del" onclick="_delModel('${escHtml(m.id)}')">${t('del')}</button></td></tr>`});
    html+='</tbody></table>'}else{html+=`<div class="empty">${t('no_models')}</div>`}
  html+=`<div id="model-form-slot"></div></div>`;
  c.innerHTML=html;
  // restore form if editing
  if(_editingModel==='__new__'){$('#model-form-slot').innerHTML=_modelForm(null,true)}
}

window._addModel=function(){_editingModel='__new__';const slot=$('#model-form-slot');if(slot)slot.innerHTML=_modelForm(null,true)};
window._editModel=async function(id){_editingModel=id;const data=await API('/api/config');const m=(data.models||[]).find(x=>x.id===id);if(!m)return;const slot=$('#model-form-slot');if(slot)slot.innerHTML=_modelForm(m,false)};
window._cancelModelForm=function(){_editingModel=null;const f=$('#model-form');if(f)f.remove()};
window._saveModel=async function(isNew){
  const id=$('#mf-id').value.trim();const prov=$('#mf-provider').value;const key=$('#mf-key').value;const model=$('#mf-model').value.trim();const url=$('#mf-url').value.trim();
  if(!id){alert('ID required');return}
  if(isNew&&!key){alert('API Key required');return}
  const entry={id,provider_name:prov,model:model||_defaultModels[prov]||'',base_url:url};
  if(key)entry.api_key=key;
  try{
    if(isNew){await fetch('/api/models',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(entry)})}
    else{await fetch('/api/models/'+encodeURIComponent(id),{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(entry)})}
    _editingModel=null;loadPage('config');
  }catch(e){alert('Error: '+e.message)}
};
window._delModel=async function(id){if(!confirm(t('confirm_del_model')+id+'?'))return;await fetch('/api/models/'+encodeURIComponent(id),{method:'DELETE'});loadPage('config')};
window._setDefault=async function(id){await fetch('/api/models/'+encodeURIComponent(id)+'/default',{method:'PUT'});loadPage('config')};
window._setFallback=async function(id){await fetch('/api/models/'+encodeURIComponent(id)+'/fallback',{method:'PUT'});loadPage('config')};
window._editDsKey=function(key){
  const valEl=$('#ds-val-'+key);if(!valEl)return;
  const cur=valEl.textContent.includes('****')?'':valEl.textContent;
  valEl.innerHTML=`<input class="form-input" id="ds-input-${key}" type="password" value="${escHtml(cur)}" style="width:200px;display:inline-block" placeholder="enter new value"><button class="btn-accent" style="margin-left:8px" onclick="_saveDsKey('${key}')">${t('save')}</button><button class="btn-del" style="margin-left:4px" onclick="loadPage('config')">${t('cancel')}</button>`;
  $(`#ds-input-${key}`).focus()};
window._saveDsKey=async function(key){
  const v=$(`#ds-input-${key}`).value.trim();if(!v)return;
  await fetch('/api/config/'+encodeURIComponent(key),{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({value:v})});
  loadPage('config')}

// ═══ Sync ═══
async function renderSync(c){
  const sync=await API('/api/sync');if(!Array.isArray(sync)||!sync.length){c.innerHTML=`<div class="empty">${t('no_data')}</div>`;return}
  const now=Date.now();
  c.innerHTML=`<div class="card fade-in"><div class="card-title">${t('sync_title')}</div>${sync.map(s=>{
    let cls='none',label=t('never_synced');
    if(s.last_synced_at){const age=(now-new Date(s.last_synced_at+'Z').getTime())/3600000;cls=age<8?'ok':'stale';label=localTime(s.last_synced_at)}
    return `<div class="sync-row"><div class="sync-dot ${cls}"></div><div style="flex:1;font-weight:600">${s.table}</div><div style="color:var(--text2)">${s.row_count||0} ${t('rows')}</div><div style="color:var(--text-dim);font-size:11px;width:180px;text-align:right">${label}</div></div>`}).join('')}</div>`}

// ═══ Background Tasks ═══
let _bgTaskId=null;
async function renderBgTasks(c){
  if(_bgTaskId)return renderBgTaskDetail(c,_bgTaskId);
  const rows=await API('/api/background-tasks');
  if(!Array.isArray(rows)||!rows.length){c.innerHTML=`<div class="empty">${t('no_bg_tasks')}</div>`;return}
  const statusPill=s=>`<span class="pill ${s==='completed'?'pill-green':(s==='failed'?'pill-red':'pill-amber')}">${s||''}</span>`;
  c.innerHTML=`<div class="tbl-wrap fade-in"><table class="tbl"><thead><tr><th>${t('th_task')}</th><th>${t('th_tool')}</th><th>${t('th_status')}</th><th>${t('bg_session')}</th><th>${t('th_created')}</th><th>${t('th_summary')}</th><th></th></tr></thead><tbody>${rows.map(r=>`
    <tr><td style="color:var(--accent);cursor:pointer" onclick="viewBgTask('${escHtml(r.task_id)}')">${escHtml(r.task_id)}</td><td>${escHtml(r.tool_name)}</td><td>${statusPill(r.status)}</td><td>${escHtml(r.session_id||'')}</td><td>${localTime(r.created_at)}</td><td style="max-width:420px;overflow:hidden;text-overflow:ellipsis">${escHtml(r.summary||'')}</td><td><span style="cursor:pointer;color:var(--accent)" onclick="viewBgTask('${escHtml(r.task_id)}')">${t('view_result')}</span></td></tr>`).join('')}</tbody></table></div>`}
window.viewBgTask=function(taskId){_bgTaskId=taskId;loadPage('bgtasks')};
window.backToBgTasks=function(){_bgTaskId=null;loadPage('bgtasks')};
async function renderBgTaskDetail(c,taskId){
  const row=await API('/api/background-tasks/'+encodeURIComponent(taskId));
  if(!row||!row.task_id){c.innerHTML=`<div class="empty">${t('no_data')}</div>`;return}
  const payload=row.result!==undefined?JSON.stringify(row.result,null,2):(row.result_json||'');
  c.innerHTML=`<div style="margin-bottom:12px"><span style="cursor:pointer;color:var(--accent)" onclick="backToBgTasks()">&larr; ${t('bg_back')}</span><span style="margin-left:12px;color:var(--text-dim)">${escHtml(row.task_id)}</span></div>
    <div class="card fade-in"><div class="card-title">${escHtml(row.tool_name||'')} · ${escHtml(row.status||'')} · ${localTime(row.created_at)}</div>
    <div style="font-size:11px;color:var(--text-dim);margin-bottom:10px">${t('bg_session')}: ${escHtml(row.session_id||'')}</div>
    <pre style="font-size:11px;line-height:1.6;color:var(--text);white-space:pre-wrap;word-break:break-all;max-height:calc(100vh - 210px);overflow-y:auto">${escHtml(payload)}</pre></div>`}

// ═══ Chat Log ═══
let _chatSessionId=null;
async function renderChatLog(c){
  if(_chatSessionId)return renderChatSession(c,_chatSessionId);
  const sessions=await API('/api/chat-sessions');
  if(!Array.isArray(sessions)||!sessions.length){c.innerHTML=`<div class="empty">${t('no_sessions')}</div>`;return}
  c.innerHTML=`<div class="tbl-wrap fade-in"><table class="tbl"><thead><tr><th>${t('th_session')}</th><th>${t('th_started')}</th><th>${t('th_ended')}</th><th>${t('th_messages')}</th><th>${t('th_tokens_in')}</th><th>${t('th_tokens_out')}</th><th>${t('th_error')}</th><th></th></tr></thead><tbody>${sessions.map(s=>{
    const hasErr=s.last_error?'<span class="pill pill-red">ERR</span>':'<span class="pill pill-green">OK</span>';
    return `<tr><td style="color:var(--accent);cursor:pointer" onclick="viewSession('${s.session_id}')">${s.session_id}</td><td>${localTime(s.started_at)}</td><td>${localTime(s.ended_at)}</td><td>${s.msg_count||0}</td><td>${(s.total_tokens_in||0).toLocaleString()}</td><td>${(s.total_tokens_out||0).toLocaleString()}</td><td>${hasErr}</td><td><span style="cursor:pointer;color:var(--accent);margin-right:8px" onclick="viewSession('${s.session_id}')">${t('view')}</span><button class="btn-del" onclick="delSession('${s.session_id}')">${t('del')}</button></td></tr>`}).join('')}</tbody></table></div>`}
window.viewSession=function(sid){_chatSessionId=sid;loadPage('chatlog')};
window.backToSessions=function(){_chatSessionId=null;loadPage('chatlog')};
window.delSession=async function(sid){if(!confirm(t('confirm_del_session')+sid+'?'))return;await fetch('/api/chat-sessions/'+sid,{method:'DELETE'});_chatSessionId=null;loadPage('chatlog')};
async function renderChatSession(c,sid){
  const logs=await API('/api/chat-log/'+sid);
  if(!Array.isArray(logs)||!logs.length){c.innerHTML=`<div class="empty">${t('no_messages')}</div>`;return}
  const rolePill=r=>{const m={user:'pill-blue',assistant:'pill-green',error:'pill-red',tool:'pill-dim'};return `<span class="pill ${m[r]||'pill-dim'}">${r}</span>`};
  c.innerHTML=`<div style="margin-bottom:12px"><span style="cursor:pointer;color:var(--accent)" onclick="backToSessions()">&larr; ${t('back')}</span><span style="margin-left:12px;color:var(--text-dim)">${t('session')}: ${sid}</span></div>
    <div class="tbl-wrap fade-in">${logs.map(l=>`<div class="mem-item"><div style="flex:1">
      <div style="margin-bottom:4px">${rolePill(l.role)} <span style="color:var(--text-dim);font-size:10px;margin-left:8px">${localTime(l.created_at)}</span>
        ${l.model?`<span style="color:var(--text-dim);font-size:10px;margin-left:8px">${l.model}</span>`:''}
        ${l.tokens_in||l.tokens_out?`<span style="color:var(--text-dim);font-size:10px;margin-left:8px">↑${l.tokens_in||0} ↓${l.tokens_out||0}</span>`:''}
        ${l.elapsed_s?`<span style="color:var(--text-dim);font-size:10px;margin-left:8px">${l.elapsed_s}s</span>`:''}</div>
      ${l.error?`<div style="color:var(--red);font-size:12px;margin-bottom:4px">${escHtml(l.error)}</div>`:''}
      <div class="mem-content">${escHtml(l.content)}</div>
      ${l.tool_calls?`<div style="color:var(--text-dim);font-size:10px;margin-top:4px">tools: ${escHtml(l.tool_calls)}</div>`:''}</div></div>`).join('')}</div>`}

// ═══ Agent Log ═══
async function renderAgentLog(c){
  const data=await API('/api/agent-log?lines=200');const log=data?.log||'';
  if(!log){c.innerHTML=`<div class="empty">${t('no_agent_log')}</div>`;return}
  c.innerHTML=`<div class="card fade-in"><div class="card-title">${t('agent_log_title')}</div><pre style="font-size:11px;line-height:1.6;color:var(--text);white-space:pre-wrap;word-break:break-all;max-height:calc(100vh - 160px);overflow-y:auto">${escHtml(log)}</pre></div>`}

// ═══ Init ═══
applyI18n();loadPage('overview');
</script>
</body>
</html>
"""
