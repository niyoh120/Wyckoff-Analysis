"""Supabase concept_heat_history 表读写。"""

from __future__ import annotations

from typing import Any

from core.constants import TABLE_CONCEPT_HEAT_HISTORY
from integrations.supabase_base import close_client as _close
from integrations.supabase_base import create_admin_client as _admin
from integrations.supabase_base import is_admin_configured as _configured


def _top_heat_items(heat: list[dict[str, Any]], top_n: int) -> list[dict[str, Any]]:
    return sorted(heat, key=lambda x: x.get("net_inflow", 0), reverse=True)[: max(int(top_n), 1)]


def upsert_concept_heat_history(trade_date: str, heat: list[dict[str, Any]], top_n: int = 20) -> int:
    """写入概念热度历史，upsert on (trade_date, concept_name)。"""
    if not _configured() or not trade_date or not heat:
        return 0
    payload = []
    for rank, item in enumerate(_top_heat_items(heat, top_n), 1):
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        payload.append(
            {
                "trade_date": trade_date,
                "concept_name": name,
                "pct": float(item.get("pct", 0.0) or 0.0),
                "net_inflow": float(item.get("net_inflow", item.get("inflow", 0.0)) or 0.0),
                "rank": rank,
                "source_id": str(item.get("cid", "") or ""),
            }
        )
    if not payload:
        return 0
    client = None
    try:
        client = _admin()
        client.table(TABLE_CONCEPT_HEAT_HISTORY).upsert(
            payload,
            on_conflict="trade_date,concept_name",
        ).execute()
        return len(payload)
    except Exception as exc:
        print(f"[concept_heat] supabase write failed: {exc}")
        return 0
    finally:
        if client is not None:
            _close(client)


def load_concept_heat_history_from_supabase(limit_days: int = 20) -> dict[str, dict]:
    """读取最近 N 个交易日的概念热度历史。"""
    if not _configured():
        return {}
    row_limit = max(int(limit_days), 1) * 50
    client = None
    try:
        client = _admin()
        resp = (
            client.table(TABLE_CONCEPT_HEAT_HISTORY)
            .select("trade_date,concept_name,pct,net_inflow,rank")
            .order("trade_date", desc=True)
            .order("rank")
            .limit(row_limit)
            .execute()
        )
    except Exception as exc:
        print(f"[concept_heat] supabase read failed: {exc}")
        return {}
    finally:
        if client is not None:
            _close(client)
    return _rows_to_history(resp.data or [], limit_days)


def _rows_to_history(rows: list[dict[str, Any]], limit_days: int) -> dict[str, dict]:
    history: dict[str, dict] = {}
    for row in rows:
        day = str(row.get("trade_date", "")).strip()
        name = str(row.get("concept_name", "")).strip()
        if not day or not name:
            continue
        history.setdefault(day, {})[name] = {
            "pct": float(row.get("pct", 0.0) or 0.0),
            "inflow": float(row.get("net_inflow", 0.0) or 0.0),
        }
    sorted_dates = sorted(history.keys(), reverse=True)[: max(int(limit_days), 1)]
    return {day: history[day] for day in sorted_dates}
