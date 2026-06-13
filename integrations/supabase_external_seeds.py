"""Supabase helpers for external seed observation rows."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from core.constants import TABLE_EXTERNAL_SEED_OBSERVATIONS
from integrations.supabase_base import (
    close_client,
    create_admin_client,
    is_admin_configured,
    require_server_write_context,
)


def _with_updated_at(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    now_iso = datetime.now(UTC).isoformat()
    return [{**row, "updated_at": now_iso} for row in rows]


def upsert_external_seed_observations(rows: list[dict[str, Any]]) -> int:
    if not rows or not is_admin_configured():
        return 0
    require_server_write_context("upsert external seed observations")
    client = None
    try:
        client = create_admin_client()
        client.table(TABLE_EXTERNAL_SEED_OBSERVATIONS).upsert(
            _with_updated_at(rows),
            on_conflict="market,trade_date,source,code",
        ).execute()
        return len(rows)
    finally:
        if client is not None:
            close_client(client)
