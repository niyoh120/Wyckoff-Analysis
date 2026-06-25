"""Local SQLite cache tables for recommendations, signals, market state, and themes."""

from __future__ import annotations

import json
import logging
import sqlite3
from typing import Any

from integrations.local_db import get_db
from integrations.local_db import save_recommendations as _save_recommendations
from integrations.local_db import save_signals as _save_signals

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Recommendation tracking
# ---------------------------------------------------------------------------


def save_recommendations(rows: list[dict]) -> int:
    return _save_recommendations(rows)


def load_recommendations(*, limit: int = 100) -> list[dict]:
    conn = get_db()
    cur = conn.execute(
        "SELECT * FROM recommendation_tracking ORDER BY recommend_date DESC LIMIT ?",
        (limit,),
    )
    return [dict(r) for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# Signal pending
# ---------------------------------------------------------------------------


def save_signals(rows: list[dict]) -> int:
    return _save_signals(rows)


def delete_recommendations(codes: list[str]) -> int:
    if not codes:
        return 0
    conn = get_db()
    placeholders = ",".join("?" for _ in codes)
    with conn:
        cur = conn.execute(
            f"DELETE FROM recommendation_tracking WHERE code IN ({placeholders})",
            codes,
        )
    return cur.rowcount


def load_signals(*, status: str | None = None, limit: int = 200) -> list[dict]:
    conn = get_db()
    try:
        if status:
            cur = conn.execute(
                "SELECT * FROM signal_pending WHERE status=? ORDER BY signal_date DESC LIMIT ?",
                (status, limit),
            )
        else:
            cur = conn.execute(
                "SELECT * FROM signal_pending ORDER BY signal_date DESC LIMIT ?",
                (limit,),
            )
    except sqlite3.OperationalError as exc:
        if "no such table: signal_pending" in str(exc).lower():
            logger.info("local signal_pending table is unavailable; returning empty signal cache")
            return []
        raise
    return [dict(r) for r in cur.fetchall()]


def load_signals_by_codes(codes: list[str]) -> dict[str, dict]:
    if not codes:
        return {}
    conn = get_db()
    ph = ",".join("?" for _ in codes)
    try:
        cur = conn.execute(
            f"SELECT * FROM signal_pending WHERE code IN ({ph}) ORDER BY signal_date DESC",
            codes,
        )
    except sqlite3.OperationalError as exc:
        if "no such table: signal_pending" in str(exc).lower():
            logger.info("local signal_pending table is unavailable; returning empty signal cache")
            return {}
        raise
    result: dict[str, dict] = {}
    for r in cur.fetchall():
        row = dict(r)
        code = row.get("code", "")
        if code not in result:
            result[code] = row
    return result


def delete_signals(codes: list[str]) -> int:
    if not codes:
        return 0
    conn = get_db()
    placeholders = ",".join("?" for _ in codes)
    with conn:
        cur = conn.execute(
            f"DELETE FROM signal_pending WHERE code IN ({placeholders})",
            codes,
        )
    return cur.rowcount


# ---------------------------------------------------------------------------
# Market signal daily
# ---------------------------------------------------------------------------


def save_market_signal(trade_date: str, data: dict) -> None:
    conn = get_db()
    with conn:
        conn.execute(
            """INSERT OR REPLACE INTO market_signal_daily
               (trade_date, data_json, synced_at) VALUES (?, ?, datetime('now'))""",
            (str(trade_date).strip(), json.dumps(data, ensure_ascii=False)),
        )


def load_latest_market_signal() -> dict | None:
    conn = get_db()
    cur = conn.execute("SELECT data_json FROM market_signal_daily ORDER BY trade_date DESC LIMIT 1")
    row = cur.fetchone()
    if not row:
        return None
    try:
        return json.loads(row["data_json"])
    except (json.JSONDecodeError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Theme radar snapshot
# ---------------------------------------------------------------------------


def save_theme_radar_snapshot(snapshot: dict[str, Any]) -> None:
    trade_date = str(snapshot.get("trade_date", "") or "").strip()
    if not trade_date:
        raise ValueError("theme radar snapshot requires trade_date")
    conn = get_db()
    with conn:
        conn.execute(
            """INSERT OR REPLACE INTO theme_radar_snapshot
               (trade_date, snapshot_json, synced_at) VALUES (?, ?, datetime('now'))""",
            (trade_date, json.dumps(snapshot, ensure_ascii=False, default=str)),
        )


def load_latest_theme_radar_snapshot() -> dict | None:
    conn = get_db()
    try:
        cur = conn.execute("SELECT snapshot_json FROM theme_radar_snapshot ORDER BY trade_date DESC LIMIT 1")
    except sqlite3.OperationalError as exc:
        if "no such table: theme_radar_snapshot" in str(exc).lower():
            return None
        raise
    row = cur.fetchone()
    if not row:
        return None
    try:
        return json.loads(row["snapshot_json"])
    except (json.JSONDecodeError, TypeError):
        return None
