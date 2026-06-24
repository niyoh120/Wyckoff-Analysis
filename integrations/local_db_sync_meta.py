"""Local SQLite sync metadata helpers."""

from __future__ import annotations

from datetime import datetime, timedelta

from integrations.local_db import get_db

# ---------------------------------------------------------------------------
# Sync metadata
# ---------------------------------------------------------------------------


def update_sync_meta(table_name: str, row_count: int) -> None:
    conn = get_db()
    with conn:
        conn.execute(
            """INSERT OR REPLACE INTO sync_meta
               (table_name, last_synced_at, row_count) VALUES (?, datetime('now'), ?)""",
            (table_name, row_count),
        )


def get_sync_meta(table_name: str) -> dict | None:
    conn = get_db()
    cur = conn.execute("SELECT * FROM sync_meta WHERE table_name=?", (table_name,))
    row = cur.fetchone()
    return dict(row) if row else None


def needs_sync(table_name: str, max_age_hours: int = 6) -> bool:
    meta = get_sync_meta(table_name)
    if not meta:
        return True
    try:
        last = datetime.fromisoformat(meta["last_synced_at"])
        return datetime.utcnow() - last > timedelta(hours=max_age_hours)
    except (ValueError, TypeError):
        return True
