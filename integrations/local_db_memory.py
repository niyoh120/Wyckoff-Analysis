"""Local SQLite agent memory persistence and retrieval."""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timedelta
from typing import Any

from integrations.local_db import get_db

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Agent memory
# ---------------------------------------------------------------------------


_MEMORY_KEEP_LIMITS: dict[str, int] = {
    "preference": 50,
    "persona": 5,
    "playbook": 20,
    "scenario": 20,
    "session": 50,
    "fact": 50,
    "stock_opinion": 30,
    "decision": 30,
    "market_view": 20,
}
_MEMORY_RECALL_WEIGHTS = {
    "fts": 0.8,
    "code": 1.2,
    "keyword": 0.25,
}
_MEMORY_DECAY_HALF_LIFE_DAYS = {
    "decision": 14.0,
    "playbook": 21.0,
    "scenario": 21.0,
    "stock_opinion": 14.0,
    "market_view": 14.0,
    "fact": 14.0,
}
_MEMORY_RETENTION_DAYS = {
    "decision": 45,
    "playbook": 60,
    "scenario": 60,
    "stock_opinion": 45,
    "market_view": 30,
    "fact": 45,
    "session": 30,
}
_MEMORY_NO_DECAY_TYPES = {"preference", "persona"}


def _memory_level(memory_type: str) -> str:
    if memory_type == "persona":
        return "L3"
    if memory_type in {"playbook", "scenario"}:
        return "L2"
    return "L1"


def _memory_metadata_text(metadata: dict[str, Any] | str | None) -> str:
    if metadata is None:
        return ""
    if isinstance(metadata, str):
        return metadata
    return json.dumps(metadata, ensure_ascii=False, default=str)


def save_memory(
    memory_type: str,
    content: str,
    codes: str = "",
    *,
    memory_level: str | None = None,
    source_ref: str = "",
    confidence: float = 1.0,
    metadata: dict[str, Any] | str | None = None,
) -> int:
    content = str(content).strip()
    if not content:
        return 0
    conn = get_db()
    level = memory_level or _memory_level(memory_type)
    metadata_text = _memory_metadata_text(metadata)
    with conn:
        existing = conn.execute(
            """SELECT id FROM agent_memory
               WHERE memory_type=? AND content=? AND codes=?
               ORDER BY created_at DESC LIMIT 1""",
            (memory_type, content, codes),
        ).fetchone()
        if existing:
            if source_ref or metadata_text:
                conn.execute(
                    """UPDATE agent_memory
                       SET source_ref = CASE WHEN ?!='' AND source_ref='' THEN ? ELSE source_ref END,
                           metadata = CASE WHEN ?!='' THEN ? ELSE metadata END
                       WHERE id=?""",
                    (source_ref, source_ref, metadata_text, metadata_text, existing["id"]),
                )
            return int(existing["id"])
        cur = conn.execute(
            """INSERT INTO agent_memory
               (memory_type, content, codes, memory_level, source_ref, confidence, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (memory_type, content, codes, level, source_ref, confidence, metadata_text),
        )
        limit = _MEMORY_KEEP_LIMITS.get(memory_type, 50)
        conn.execute(
            """DELETE FROM agent_memory WHERE memory_type = ? AND id NOT IN (
                   SELECT id FROM agent_memory WHERE memory_type = ?
                   ORDER BY created_at DESC LIMIT ?
               )""",
            (memory_type, memory_type, limit),
        )
        return cur.lastrowid or 0


def get_memory_by_id(memory_id: int) -> dict | None:
    conn = get_db()
    cur = conn.execute("SELECT * FROM agent_memory WHERE id=?", (memory_id,))
    row = cur.fetchone()
    return dict(row) if row else None


def search_memory(
    *,
    codes: list[str] | None = None,
    keyword: str | None = None,
    memory_level: str | None = None,
    since: str | None = None,
    limit: int = 10,
) -> list[dict]:
    conn = get_db()
    clauses: list[str] = []
    params: list[Any] = []
    if codes:
        or_parts = []
        for c in codes:
            or_parts.append("codes LIKE ?")
            params.append(f"%{c}%")
        clauses.append(f"({' OR '.join(or_parts)})")
    if keyword:
        clauses.append("content LIKE ?")
        params.append(f"%{keyword}%")
    if memory_level:
        clauses.append("memory_level=?")
        params.append(memory_level)
    if since:
        clauses.append("created_at >= ?")
        params.append(since)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    cur = conn.execute(
        f"SELECT * FROM agent_memory {where} ORDER BY created_at DESC LIMIT ?",
        params + [limit],
    )
    return [dict(r) for r in cur.fetchall()]


def get_recent_memories(
    *,
    memory_type: str | None = None,
    memory_level: str | None = None,
    since: str | None = None,
    limit: int = 20,
) -> list[dict]:
    conn = get_db()
    clauses: list[str] = []
    params: list[Any] = []
    if memory_type:
        clauses.append("memory_type=?")
        params.append(memory_type)
    if memory_level:
        clauses.append("memory_level=?")
        params.append(memory_level)
    if since:
        clauses.append("created_at >= ?")
        params.append(since)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    cur = conn.execute(
        f"SELECT * FROM agent_memory {where} ORDER BY created_at DESC LIMIT ?",
        params + [limit],
    )
    return [dict(r) for r in cur.fetchall()]


def search_memory_by_keywords(keywords: list[str], limit: int = 5) -> list[dict]:
    conn = get_db()
    if not keywords:
        return []
    clauses = ["content LIKE ?" for _ in keywords]
    params = [f"%{kw}%" for kw in keywords]
    cur = conn.execute(
        f"SELECT * FROM agent_memory WHERE ({' OR '.join(clauses)}) ORDER BY created_at DESC LIMIT ?",
        params + [limit],
    )
    return [dict(r) for r in cur.fetchall()]


def search_memory_fts(query: str, limit: int = 10) -> list[dict]:
    """FTS5 全文检索记忆。"""
    conn = get_db()
    try:
        cur = conn.execute(
            """SELECT m.*, bm25(agent_memory_fts) AS rank
               FROM agent_memory_fts fts
               JOIN agent_memory m ON m.id = fts.rowid
               WHERE agent_memory_fts MATCH ?
               ORDER BY rank
               LIMIT ?""",
            (query, limit),
        )
        return [dict(r) for r in cur.fetchall()]
    except Exception:
        return []


def _memory_codes(row: dict) -> set[str]:
    raw = str(row.get("codes", "") or "")
    return {part.strip() for part in raw.split(",") if len(part.strip()) == 6 and part.strip().isdigit()}


def _scope_memory_results(candidates: dict[int, dict], codes: list[str] | None) -> dict[int, dict]:
    current_codes = set(codes or [])
    scoped: dict[int, dict] = {}
    for mid, row in candidates.items():
        mem_codes = _memory_codes(row)
        if not mem_codes or mem_codes & current_codes:
            scoped[mid] = row
    return scoped


def _memory_decay(row: dict, age_days: float, fallback_half_life_days: float) -> float:
    import math

    if row.get("memory_type") in _MEMORY_NO_DECAY_TYPES:
        return 1.0
    half_life = _MEMORY_DECAY_HALF_LIFE_DAYS.get(str(row.get("memory_type") or ""), fallback_half_life_days)
    return math.pow(2, -age_days / max(half_life, 1.0))


def _memory_age_days(row: dict) -> float | None:
    created = row.get("created_at", "")
    if not created:
        return None
    try:
        dt = datetime.fromisoformat(str(created))
    except (ValueError, TypeError):
        return None
    return max((datetime.utcnow() - dt).total_seconds() / 86400, 0)


def search_memory_hybrid(
    *,
    query_text: str,
    codes: list[str] | None = None,
    keywords: list[str] | None = None,
    limit: int = 8,
    decay_half_life_days: float = 14.0,
    strict_code_scope: bool = False,
) -> list[dict]:
    """Hybrid search: FTS5 全文 + 代码匹配 + 关键词 LIKE + 时间衰减加权。

    返回按综合得分排序的记忆列表，每条带 _score 字段。
    """
    candidates: dict[int, dict] = {}

    def _merge(items: list[dict], source_weight: float) -> None:
        for m in items:
            mid = m["id"]
            if mid not in candidates:
                m["_score"] = source_weight
                candidates[mid] = m
            else:
                candidates[mid]["_score"] = max(candidates[mid].get("_score", 0), source_weight)

    # 1. FTS5 全文检索（最高权重）
    if query_text and len(query_text.strip()) >= 2:
        fts_results = search_memory_fts(query_text, limit=limit * 2)
        _merge(fts_results, _MEMORY_RECALL_WEIGHTS["fts"])

    # 2. 股票代码精确匹配
    if codes:
        code_results = search_memory(codes=codes, limit=limit * 2)
        _merge(code_results, _MEMORY_RECALL_WEIGHTS["code"])

    # 3. 关键词 LIKE 检索
    if keywords:
        kw_results = search_memory_by_keywords(keywords, limit=limit * 2)
        _merge(kw_results, _MEMORY_RECALL_WEIGHTS["keyword"])

    if strict_code_scope:
        candidates = _scope_memory_results(candidates, codes)

    for m in candidates.values():
        age_days = _memory_age_days(m)
        decay = 0.5 if age_days is None else _memory_decay(m, age_days, decay_half_life_days)
        m["_score"] = m.get("_score", 0.5) * decay

    # 按得分排序
    ranked = sorted(candidates.values(), key=lambda x: x.get("_score", 0), reverse=True)
    return ranked[:limit]


def prune_agent_memory_for_connection(conn: sqlite3.Connection, *, fallback_keep_days: int) -> int:
    deleted = 0
    for memory_type, keep_days in _MEMORY_RETENTION_DAYS.items():
        cutoff = (datetime.utcnow() - timedelta(days=keep_days)).isoformat()
        cur = conn.execute(
            "DELETE FROM agent_memory WHERE memory_type=? AND created_at < ?",
            (memory_type, cutoff),
        )
        deleted += cur.rowcount
    cutoff = (datetime.utcnow() - timedelta(days=fallback_keep_days)).isoformat()
    cur = conn.execute(
        "DELETE FROM agent_memory WHERE created_at < ? AND memory_type NOT IN (?, ?)",
        (cutoff, "preference", "persona"),
    )
    return deleted + cur.rowcount


def prune_memories(keep_days: int = 90) -> int:
    conn = get_db()
    with conn:
        return prune_agent_memory_for_connection(conn, fallback_keep_days=keep_days)
