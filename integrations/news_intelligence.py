"""News intelligence pool cache, auto-fetch, and query interface."""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.request
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
    conn.commit()


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


def refresh_intelligence_pool(force: bool = False) -> None:
    """Pull NewsNow feeds and load into local database with a 60m cooldown."""
    global _last_fetch_time
    now = time.monotonic()

    # Check auto fetch enabled
    enabled = os.getenv("NEWS_INTEL_AUTO_FETCH_ENABLED", "false").strip().lower() == "true"
    if not enabled and not force:
        return

    if not force and _last_fetch_time > 0 and (now - _last_fetch_time) < _COOLDOWN_SECONDS:
        return

    logger.info("[intel] Refreshing local news intelligence pool...")
    base_url = os.getenv("NEWSNOW_BASE_URL", "https://newsnow.busiyi.world").strip("/")

    total_new_items = 0
    for source in DEFAULT_NEWSNOW_SOURCES:
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
        except Exception as e:
            logger.warning("[intel] Failed to fetch newsnow feed '%s': %s", source, e)

    logger.info("[intel] News intelligence pool refresh complete. New items: %d", total_new_items)
    _last_fetch_time = now
