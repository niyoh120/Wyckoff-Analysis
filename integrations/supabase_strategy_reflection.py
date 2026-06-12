"""Supabase helpers for strategy reflection shadow artifacts."""

from __future__ import annotations

from typing import Any

from core.constants import TABLE_STRATEGY_POLICY_CANDIDATES, TABLE_STRATEGY_REFLECTIONS
from integrations.supabase_base import close_client as _close
from integrations.supabase_base import create_admin_client as _admin
from integrations.supabase_base import is_admin_configured as _configured
from integrations.supabase_base import require_server_write_context


def _upsert_rows(table: str, rows: list[dict[str, Any]], conflict: str) -> int:
    if not _configured() or not rows:
        return 0
    require_server_write_context(f"upsert {table}")
    client = None
    try:
        client = _admin()
        client.table(table).upsert(rows, on_conflict=conflict).execute()
        return len(rows)
    finally:
        if client is not None:
            _close(client)


def upsert_strategy_reflection(row: dict[str, Any]) -> int:
    return _upsert_rows(
        TABLE_STRATEGY_REFLECTIONS,
        [row],
        "market,as_of_date,horizon_days",
    )


def upsert_strategy_policy_candidate(row: dict[str, Any] | None) -> int:
    if not row:
        return 0
    return _upsert_rows(
        TABLE_STRATEGY_POLICY_CANDIDATES,
        [row],
        "market,as_of_date",
    )
