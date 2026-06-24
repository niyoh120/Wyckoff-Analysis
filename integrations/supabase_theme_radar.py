"""Supabase theme_radar_snapshot table helpers."""

from __future__ import annotations

import json
import logging
from typing import Any

from core.constants import TABLE_THEME_RADAR_SNAPSHOT
from integrations.supabase_base import close_client as _close
from integrations.supabase_base import create_admin_client as _admin
from integrations.supabase_base import create_read_client as _read
from integrations.supabase_base import is_admin_configured as _configured
from integrations.supabase_base import require_server_write_context

logger = logging.getLogger(__name__)


def upsert_theme_radar_snapshot(snapshot: dict[str, Any]) -> int:
    """Write one theme radar snapshot, upsert on trade_date."""
    trade_date = str(snapshot.get("trade_date", "") or "").strip()
    if not _configured() or not trade_date:
        return 0
    require_server_write_context("upsert theme_radar_snapshot")
    payload = {
        "trade_date": trade_date,
        "snapshot_json": snapshot,
        "top_themes": _top_theme_names(snapshot),
        "top_candidates": _top_candidate_codes(snapshot),
    }
    client = None
    try:
        client = _admin()
        client.table(TABLE_THEME_RADAR_SNAPSHOT).upsert(payload, on_conflict="trade_date").execute()
        return 1
    except Exception as exc:
        logger.warning("theme radar write failed: %s", exc)
        return 0
    finally:
        if client is not None:
            _close(client)


def load_latest_theme_radar_snapshot_from_supabase() -> dict | None:
    """Load the latest persisted theme radar snapshot."""
    client = None
    try:
        client = _read()
        resp = (
            client.table(TABLE_THEME_RADAR_SNAPSHOT)
            .select("snapshot_json")
            .order("trade_date", desc=True)
            .limit(1)
            .execute()
        )
    except Exception as exc:
        logger.warning("theme radar read failed: %s", exc)
        return None
    finally:
        if client is not None:
            _close(client)
    rows = resp.data or []
    return _decode_snapshot(rows[0].get("snapshot_json")) if rows else None


def _top_theme_names(snapshot: dict[str, Any]) -> list[str]:
    return [str(item.get("theme", "")).strip() for item in (snapshot.get("themes") or [])[:8] if item.get("theme")]


def _top_candidate_codes(snapshot: dict[str, Any]) -> list[str]:
    return [
        str(item.get("code", "")).strip()
        for item in (snapshot.get("strategic_candidates") or [])[:20]
        if item.get("code")
    ]


def _decode_snapshot(raw: Any) -> dict | None:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            return None
    return None
