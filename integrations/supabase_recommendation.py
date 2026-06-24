"""Supabase recommendation_tracking table adapter."""

from __future__ import annotations

import logging
from typing import Any

from core.constants import TABLE_RECOMMENDATION_TRACKING
from integrations.recommendation_tracking_common import chunked
from integrations.supabase_base import create_read_client

logger = logging.getLogger(__name__)


def fetch_recommendation_tracking_records(
    client,
    select_expr: str = "*",
    *,
    page_size: int = 1000,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    page = max(min(int(page_size), 1000), 1)
    start = 0
    while True:
        resp = (
            client.table(TABLE_RECOMMENDATION_TRACKING)
            .select(select_expr)
            .order("recommend_date", desc=False)
            .order("id", desc=False)
            .range(start, start + page - 1)
            .execute()
        )
        batch = resp.data or []
        records.extend(batch)
        if len(batch) < page:
            return records
        start += page


def upsert_recommendation_tracking_updates(client, updates: list[dict[str, Any]], batch_size: int = 500) -> int:
    written = 0
    rows = [row for row in updates if row.get("code") is not None and row.get("recommend_date") is not None]
    for batch in chunked(rows, max(min(int(batch_size), 1000), 1)):
        client.table(TABLE_RECOMMENDATION_TRACKING).upsert(batch, on_conflict="code,recommend_date").execute()
        written += len(batch)
    return written


def upsert_recommendation_tracking_price_updates(client, updates: list[dict[str, Any]], batch_size: int = 50) -> int:
    written = 0
    rows = [row for row in updates if row.get("id") is not None]
    for batch in chunked(rows, max(int(batch_size), 1)):
        client.table(TABLE_RECOMMENDATION_TRACKING).upsert(batch, on_conflict="id").execute()
        written += len(batch)
    return written


def load_recommendation_tracking(limit: int = 1000, client=None) -> list[dict[str, Any]]:
    try:
        db = client or create_read_client()
        resp = (
            db.table(TABLE_RECOMMENDATION_TRACKING)
            .select("*")
            .order("recommend_date", desc=True)
            .limit(limit)
            .execute()
        )
        return resp.data or []
    except Exception as exc:
        logger.warning("load_recommendation_tracking failed: %s", exc)
        return []
