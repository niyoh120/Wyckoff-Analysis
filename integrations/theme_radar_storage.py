"""Persistence policy for theme radar snapshots."""

from __future__ import annotations

from typing import Any


def persist_theme_radar_snapshot(snapshot: dict[str, Any], *, local_fallback: bool = True) -> dict[str, int | str]:
    """Persist to Supabase first; optionally fall back to local SQLite."""
    result: dict[str, int | str] = {"supabase": 0, "sqlite": 0}
    try:
        from integrations.supabase_theme_radar import upsert_theme_radar_snapshot

        result["supabase"] = upsert_theme_radar_snapshot(snapshot)
    except Exception as exc:
        result["error"] = str(exc)
    if result["supabase"] or not local_fallback:
        return result
    try:
        from integrations.local_db import init_db, save_theme_radar_snapshot

        init_db()
        save_theme_radar_snapshot(snapshot)
        result["sqlite"] = 1
    except Exception as exc:
        result["error"] = str(exc)
    return result


def load_latest_theme_radar_snapshot() -> dict[str, Any] | None:
    """Load the latest snapshot from Supabase, then local SQLite."""
    try:
        from integrations.supabase_theme_radar import load_latest_theme_radar_snapshot_from_supabase

        snapshot = load_latest_theme_radar_snapshot_from_supabase()
        if snapshot:
            return snapshot
    except Exception:
        pass
    try:
        from integrations.local_db import init_db
        from integrations.local_db import load_latest_theme_radar_snapshot as load_local

        init_db()
        return load_local()
    except Exception:
        return None
