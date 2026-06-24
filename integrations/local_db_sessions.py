"""Local SQLite chat session listing and deletion helpers."""

from __future__ import annotations

from integrations.local_db import get_db

# ---------------------------------------------------------------------------
# Chat sessions
# ---------------------------------------------------------------------------


def delete_chat_session(session_id: str) -> int:
    conn = get_db()
    with conn:
        cur = conn.execute(
            "DELETE FROM chat_log WHERE session_id=?",
            (session_id,),
        )
    return cur.rowcount


def list_chat_sessions(limit: int = 50) -> list[dict]:
    """返回最近的会话列表，每个会话的首条用户消息作为摘要。"""
    conn = get_db()
    cur = conn.execute(
        """SELECT session_id,
                  MIN(created_at) AS started_at,
                  MAX(created_at) AS ended_at,
                  COUNT(*) AS msg_count,
                  SUM(tokens_in) AS total_tokens_in,
                  SUM(tokens_out) AS total_tokens_out,
                  MAX(CASE WHEN error != '' THEN error ELSE NULL END) AS last_error,
                  MAX(CASE WHEN role='assistant' THEN model ELSE NULL END) AS model,
                  (SELECT content FROM chat_log c2 WHERE c2.session_id=chat_log.session_id AND c2.role='user' ORDER BY c2.created_at ASC LIMIT 1) AS first_user_msg,
                  SUM(elapsed_s) AS total_elapsed_s
           FROM chat_log
           GROUP BY session_id
           ORDER BY MAX(created_at) DESC
           LIMIT ?""",
        (limit,),
    )
    return [dict(r) for r in cur.fetchall()]
