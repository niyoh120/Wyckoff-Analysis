"""Local SQLite cleanup helpers."""

from __future__ import annotations

from datetime import datetime, timedelta

from integrations.local_db import get_db
from integrations.local_db_memory import prune_agent_memory_for_connection

# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


def cleanup_old_records(days: int = 30) -> dict[str, int]:
    """删除 N 天前的 chat_log / background_task_result / agent_memory 记录。"""
    conn = get_db()
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    deleted: dict[str, int] = {}
    with conn:
        for table in ("chat_log", "background_task_result", "workflow_run"):
            cur = conn.execute(
                f"DELETE FROM {table} WHERE created_at < ?",
                (cutoff,),
            )
            deleted[table] = cur.rowcount
        cur = conn.execute(
            """DELETE FROM workflow_event
               WHERE run_id NOT IN (SELECT run_id FROM workflow_run)""",
        )
        deleted["workflow_event"] = cur.rowcount
        deleted["agent_memory"] = prune_agent_memory_for_connection(conn, fallback_keep_days=days)
    return deleted
