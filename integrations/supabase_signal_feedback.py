"""Supabase read/write helpers for signal feedback tables."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from typing import Any

from core.constants import (
    TABLE_SIGNAL_HEALTH_DAILY,
    TABLE_SIGNAL_OBSERVATIONS,
    TABLE_SIGNAL_OUTCOMES,
    TABLE_SIGNAL_POLICY_SHADOW_RUNS,
    TABLE_SIGNAL_REGISTRY,
)
from integrations.supabase_base import close_client as _close
from integrations.supabase_base import create_admin_client as _admin
from integrations.supabase_base import is_admin_configured as _configured
from integrations.supabase_base import require_server_write_context

logger = logging.getLogger(__name__)

OPTIONAL_SIGNAL_OBSERVATION_COLUMNS = (
    "profile_tag",
    "stage_tag",
    "trigger_tags",
    "selection_mode",
    "policy_version",
    "candidate_rank",
    "features_json",
)


def _recent_cutoff(days: int) -> str:
    return (date.today() - timedelta(days=max(int(days), 1))).isoformat()


def _looks_like_schema_miss(exc: Exception) -> bool:
    text = str(exc).lower()
    return "column" in text or "schema cache" in text or "could not find" in text


def _drop_optional_columns(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    clean = []
    for row in rows:
        r = dict(row)
        for column in OPTIONAL_SIGNAL_OBSERVATION_COLUMNS:
            r.pop(column, None)
        clean.append(r)
    return clean


def _execute_upsert(
    table: str,
    rows: list[dict[str, Any]],
    conflict: str,
    *,
    raise_on_error: bool = True,
) -> int:
    if not _configured() or not rows:
        return 0
    require_server_write_context(f"upsert {table}")
    client = None
    try:
        client = _admin()
        try:
            client.table(table).upsert(rows, on_conflict=conflict).execute()
        except Exception as exc:
            if table != TABLE_SIGNAL_OBSERVATIONS or not _looks_like_schema_miss(exc):
                raise
            client.table(table).upsert(_drop_optional_columns(rows), on_conflict=conflict).execute()
        return len(rows)
    except Exception as exc:
        logger.warning("upsert %s failed: %s", table, exc)
        if raise_on_error:
            raise
        return 0
    finally:
        if client is not None:
            _close(client)


def upsert_signal_observations(rows: list[dict[str, Any]]) -> int:
    return _execute_upsert(TABLE_SIGNAL_OBSERVATIONS, rows, "market,trade_date,code,signal_type")


def upsert_signal_outcomes(rows: list[dict[str, Any]]) -> int:
    return _execute_upsert(TABLE_SIGNAL_OUTCOMES, rows, "observation_id,horizon_days")


def upsert_signal_health(rows: list[dict[str, Any]]) -> int:
    return _execute_upsert(TABLE_SIGNAL_HEALTH_DAILY, rows, "market,as_of_date,signal_type,regime,horizon_days")


def upsert_signal_registry(rows: list[dict[str, Any]]) -> int:
    return _execute_upsert(TABLE_SIGNAL_REGISTRY, rows, "market,signal_type")


def upsert_policy_shadow_run(row: dict[str, Any]) -> int:
    return _execute_upsert(TABLE_SIGNAL_POLICY_SHADOW_RUNS, [row], "market,trade_date", raise_on_error=False)


def load_recent_signal_observations(days: int = 90, limit: int = 5000, market: str = "cn") -> list[dict[str, Any]]:
    if not _configured():
        return []
    client = None
    try:
        client = _admin()
        resp = (
            client.table(TABLE_SIGNAL_OBSERVATIONS)
            .select("*")
            .eq("market", market)
            .gte("trade_date", _recent_cutoff(days))
            .order("trade_date", desc=True)
            .limit(max(int(limit), 1))
            .execute()
        )
        return resp.data or []
    except Exception as exc:
        logger.warning("load observations failed: %s", exc)
        return []
    finally:
        if client is not None:
            _close(client)


def load_recent_signal_outcomes(days: int = 180, limit: int = 20000, market: str = "cn") -> list[dict[str, Any]]:
    if not _configured():
        return []
    client = None
    try:
        client = _admin()
        resp = (
            client.table(TABLE_SIGNAL_OUTCOMES)
            .select("*")
            .eq("market", market)
            .gte("trade_date", _recent_cutoff(days))
            .order("trade_date", desc=True)
            .limit(max(int(limit), 1))
            .execute()
        )
        return resp.data or []
    except Exception as exc:
        logger.warning("load outcomes failed: %s", exc)
        return []
    finally:
        if client is not None:
            _close(client)


def _latest_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest_date = ""
    selected: dict[tuple[str, str, int], dict[str, Any]] = {}
    for row in rows:
        row_date = str(row.get("as_of_date") or "")
        if row_date > latest_date:
            latest_date = row_date
            selected = {}
        if row_date == latest_date:
            key = (str(row.get("signal_type")), str(row.get("regime")), int(row.get("horizon_days") or 0))
            selected[key] = row
    return list(selected.values())


def load_signal_health_snapshot(market: str = "cn", limit: int = 1000) -> list[dict[str, Any]]:
    if not _configured():
        return []
    client = None
    try:
        client = _admin()
        resp = (
            client.table(TABLE_SIGNAL_HEALTH_DAILY)
            .select("*")
            .eq("market", market)
            .order("as_of_date", desc=True)
            .limit(max(int(limit), 1))
            .execute()
        )
        return _latest_rows(resp.data or [])
    except Exception as exc:
        logger.warning("load health failed: %s", exc)
        return []
    finally:
        if client is not None:
            _close(client)


def load_signal_registry(market: str = "cn") -> list[dict[str, Any]]:
    if not _configured():
        return []
    client = None
    try:
        client = _admin()
        resp = client.table(TABLE_SIGNAL_REGISTRY).select("*").eq("market", market).execute()
        return resp.data or []
    except Exception as exc:
        logger.warning("load registry failed: %s", exc)
        return []
    finally:
        if client is not None:
            _close(client)


def load_policy_shadow_runs(days: int = 30, limit: int = 1000, market: str = "cn") -> list[dict[str, Any]]:
    if not _configured():
        return []
    client = None
    try:
        client = _admin()
        resp = (
            client.table(TABLE_SIGNAL_POLICY_SHADOW_RUNS)
            .select("*")
            .eq("market", market)
            .gte("trade_date", _recent_cutoff(days))
            .order("trade_date", desc=True)
            .limit(max(int(limit), 1))
            .execute()
        )
        return resp.data or []
    except Exception as exc:
        logger.warning("load policy shadow failed: %s", exc)
        return []
    finally:
        if client is not None:
            _close(client)


def touch_registry_defaults(market: str, signal_types: list[str]) -> int:
    now_iso = datetime.now(UTC).isoformat()
    rows = [
        {
            "market": market,
            "signal_type": signal_type,
            "track": "Trend" if signal_type in {"sos", "evr", "trend_pullback"} else "Accum",
            "status": "ACTIVE",
            "weight_multiplier": 1.0,
            "reason": "default active",
            "updated_at": now_iso,
        }
        for signal_type in signal_types
    ]
    return upsert_signal_registry(rows)
