"""News intelligence pool cache, auto-fetch, and query interface."""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.request
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

_last_fetch_time = 0.0
_COOLDOWN_SECONDS = 3600  # 60 minutes cooldown

DEFAULT_NEWSNOW_SOURCES = [
    "cls-hot",
    "xueqiu-hotstock",
    "wallstreetcn-quick",
    "jin10",
    "gelonghui",
]


def configured_news_sources() -> list[str]:
    """Return deduplicated source ids, optionally narrowed by environment config."""
    raw = os.getenv("NEWSNOW_SOURCES", "").strip()
    sources = raw.replace("，", ",").split(",") if raw else DEFAULT_NEWSNOW_SOURCES
    return list(dict.fromkeys(item.strip() for item in sources if item.strip()))


def init_intel_db() -> None:
    """Create intelligence_items table in local database if not exists."""
    from integrations.local_db import get_db

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS intelligence_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            url TEXT UNIQUE,
            source TEXT,
            pub_date TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            market TEXT,
            content TEXT
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS intelligence_source_state (
            source TEXT PRIMARY KEY,
            enabled INTEGER NOT NULL DEFAULT 1,
            last_fetched_at TEXT,
            last_success_at TEXT,
            last_error TEXT,
            last_item_count INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.commit()


def _record_source_state(source: str, *, item_count: int = 0, error: str = "") -> None:
    from integrations.local_db import get_db

    init_intel_db()
    now = datetime.now(UTC).isoformat(timespec="seconds")
    conn = get_db()
    conn.execute(
        """INSERT INTO intelligence_source_state
           (source, enabled, last_fetched_at, last_success_at, last_error, last_item_count)
           VALUES (?, 1, ?, ?, ?, ?)
           ON CONFLICT(source) DO UPDATE SET
             last_fetched_at=excluded.last_fetched_at,
             last_success_at=excluded.last_success_at,
             last_error=excluded.last_error,
             last_item_count=excluded.last_item_count""",
        (source, now, now if not error else None, error[:500], max(int(item_count), 0)),
    )
    conn.commit()


def intelligence_status() -> dict[str, Any]:
    """Expose source freshness and the auto-refresh cooldown without fetching."""
    from integrations.local_db import get_db

    init_intel_db()
    conn = get_db()
    rows = conn.execute(
        "SELECT source, enabled, last_fetched_at, last_success_at, last_error, last_item_count FROM intelligence_source_state"
    ).fetchall()
    saved = {str(row[0]): row for row in rows}
    now = time.monotonic()
    cooldown_remaining = max(0, int(_COOLDOWN_SECONDS - (now - _last_fetch_time))) if _last_fetch_time else 0
    sources = []
    for source in configured_news_sources():
        row = saved.get(source)
        sources.append(
            {
                "source": source,
                "enabled": True if row is None else bool(row[1]),
                "last_fetched_at": "" if row is None else str(row[2] or ""),
                "last_success_at": "" if row is None else str(row[3] or ""),
                "last_error": "" if row is None else str(row[4] or ""),
                "last_item_count": 0 if row is None else int(row[5] or 0),
            }
        )
    return {
        "enabled": os.getenv("NEWS_INTEL_AUTO_FETCH_ENABLED", "false").strip().lower() == "true",
        "cooldown_seconds": _COOLDOWN_SECONDS,
        "cooldown_remaining": cooldown_remaining,
        "sources": sources,
    }


def save_intelligence_items(items: list[dict[str, Any]]) -> int:
    """Upsert news items into SQLite."""
    from integrations.local_db import get_db

    init_intel_db()
    conn = get_db()
    cursor = conn.cursor()
    inserted = 0
    for item in items:
        try:
            cursor.execute(
                """
                INSERT OR IGNORE INTO intelligence_items (title, url, source, pub_date, market, content)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    item.get("title", ""),
                    item.get("url", ""),
                    item.get("source", ""),
                    item.get("pub_date", ""),
                    item.get("market", "cn"),
                    item.get("content", ""),
                ),
            )
            if cursor.rowcount > 0:
                inserted += 1
        except Exception as e:
            logger.debug("Failed to insert intel item: %s", e)
    conn.commit()
    return inserted


def query_intelligence_by_keyword(keyword: str, limit: int = 20) -> list[dict[str, Any]]:
    """Retrieve items containing matching keywords from SQLite."""
    from integrations.local_db import get_db

    init_intel_db()
    conn = get_db()
    cursor = conn.cursor()
    pattern = f"%{keyword}%"
    cursor.execute(
        """
        SELECT title, url, source, pub_date, content FROM intelligence_items
        WHERE title LIKE ? OR content LIKE ?
        ORDER BY pub_date DESC, created_at DESC
        LIMIT ?
        """,
        (pattern, pattern, limit),
    )
    rows = cursor.fetchall()
    return [
        {
            "title": r[0],
            "url": r[1],
            "source": r[2],
            "pub_date": r[3],
            "content": r[4],
        }
        for r in rows
    ]


def query_news_intelligence(query: str = "", limit: int = 10, refresh: bool = False) -> dict[str, Any]:
    """Return cited local intelligence items plus source freshness metadata."""
    refresh_result = refresh_intelligence_pool(force=True) if refresh else None
    items = query_intelligence_by_keyword(query.strip(), max(min(int(limit), 50), 1)) if query.strip() else []
    return {
        "query": query.strip(),
        "items": items,
        "source_status": intelligence_status(),
        "refresh": refresh_result,
    }


def refresh_intelligence_pool(force: bool = False) -> dict[str, Any]:
    """Pull NewsNow feeds and load into local database with a 60m cooldown."""
    global _last_fetch_time
    now = time.monotonic()

    # Check auto fetch enabled
    enabled = os.getenv("NEWS_INTEL_AUTO_FETCH_ENABLED", "false").strip().lower() == "true"
    if not enabled and not force:
        return {**intelligence_status(), "refreshed": False, "reason": "disabled", "new_items": 0}

    if not force and _last_fetch_time > 0 and (now - _last_fetch_time) < _COOLDOWN_SECONDS:
        return {**intelligence_status(), "refreshed": False, "reason": "cooldown", "new_items": 0}

    logger.info("[intel] Refreshing local news intelligence pool...")
    base_url = os.getenv("NEWSNOW_BASE_URL", "https://newsnow.busiyi.world").strip("/")

    total_new_items = 0
    for source in configured_news_sources():
        try:
            url = f"{base_url}/api/s?id={source}"
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "WyckoffTradingAgent/1.0"},
            )
            with urllib.request.urlopen(req, timeout=8) as response:
                res_data = json.loads(response.read().decode("utf-8"))
                raw_items = res_data.get("items", []) or []

                parsed_items = []
                for item in raw_items:
                    link = item.get("url") or item.get("mobileUrl") or ""
                    pub_date = item.get("pubDate") or item.get("date") or ""
                    parsed_items.append(
                        {
                            "title": item.get("title", ""),
                            "url": link,
                            "source": source,
                            "pub_date": pub_date,
                            "market": "cn",
                            "content": item.get("content") or item.get("description") or "",
                        }
                    )

                if parsed_items:
                    new_count = save_intelligence_items(parsed_items)
                    total_new_items += new_count
                _record_source_state(source, item_count=len(parsed_items))
        except Exception as e:
            logger.warning("[intel] Failed to fetch newsnow feed '%s': %s", source, e)
            _record_source_state(source, error=str(e))

    logger.info("[intel] News intelligence pool refresh complete. New items: %d", total_new_items)
    _last_fetch_time = now
    return {**intelligence_status(), "refreshed": True, "reason": "ok", "new_items": total_new_items}
