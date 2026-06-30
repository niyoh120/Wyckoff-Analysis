"""Local SQLite chat log and background task persistence."""

from __future__ import annotations

import json
from typing import Any

from integrations.local_db import background_task_result_summary, get_db

# ---------------------------------------------------------------------------
# Chat log — 对话记录
# ---------------------------------------------------------------------------


def save_chat_log(
    session_id: str,
    role: str,
    content: str,
    *,
    model: str = "",
    provider: str = "",
    tokens_in: int = 0,
    tokens_out: int = 0,
    elapsed_s: float = 0,
    error: str = "",
    tool_calls_json: str = "",
    metadata_json: str = "",
) -> int:
    conn = get_db()
    with conn:
        cur = conn.execute(
            """INSERT INTO chat_log
               (session_id, role, content, model, provider,
                tokens_in, tokens_out, elapsed_s, error, tool_calls, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                session_id,
                role,
                content,
                model,
                provider,
                tokens_in,
                tokens_out,
                elapsed_s,
                error,
                tool_calls_json,
                metadata_json,
            ),
        )
        return cur.lastrowid or 0


def load_chat_logs(*, session_id: str | None = None, limit: int = 200) -> list[dict]:
    conn = get_db()
    if session_id:
        cur = conn.execute(
            "SELECT * FROM chat_log WHERE session_id=? ORDER BY created_at ASC LIMIT ?",
            (session_id, limit),
        )
    else:
        cur = conn.execute(
            "SELECT * FROM chat_log ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
    return [dict(r) for r in cur.fetchall()]


def save_background_task_result(
    task_id: str,
    tool_name: str,
    result: Any,
    *,
    session_id: str = "",
    status: str = "completed",
) -> int:
    """Persist a completed CLI background task result for dashboard history."""
    result_json = json.dumps(result, ensure_ascii=False, default=str)
    summary = background_task_result_summary(tool_name, task_id, result, result_json)
    conn = get_db()
    with conn:
        cur = conn.execute(
            """INSERT OR REPLACE INTO background_task_result
               (task_id, session_id, tool_name, status, result_json, summary, created_at)
               VALUES (?, ?, ?, ?, ?, ?, datetime('now'))""",
            (task_id, session_id, tool_name, status, result_json, summary),
        )
        return cur.lastrowid or 0


def load_background_task_results(*, limit: int = 100) -> list[dict]:
    conn = get_db()
    cur = conn.execute(
        """SELECT id, task_id, session_id, tool_name, status, summary, created_at
           FROM background_task_result
           ORDER BY created_at DESC
           LIMIT ?""",
        (min(max(limit, 1), 500),),
    )
    return [dict(r) for r in cur.fetchall()]


def load_background_task_result(task_id: str) -> dict | None:
    conn = get_db()
    cur = conn.execute(
        "SELECT * FROM background_task_result WHERE task_id=?",
        (task_id,),
    )
    row = cur.fetchone()
    if not row:
        return None
    data = dict(row)
    try:
        data["result"] = json.loads(data.get("result_json") or "{}")
    except json.JSONDecodeError:
        data["result"] = data.get("result_json") or ""
    return data


def get_session_preview(session_id: str) -> str:
    """取会话首条用户消息作为摘要预览。"""
    conn = get_db()
    cur = conn.execute(
        "SELECT content FROM chat_log WHERE session_id=? AND role='user' ORDER BY created_at ASC LIMIT 1",
        (session_id,),
    )
    row = cur.fetchone()
    if row:
        t = (row["content"] or "").strip().replace("\n", " ")
        return t[:60] + ("…" if len(t) > 60 else "")
    return "(空会话)"
