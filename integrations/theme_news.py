"""Optional public-news collectors for the theme radar."""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from typing import Any

import requests

from core.theme_radar import infer_event_themes
from utils.env import env_flag

DEFAULT_GDELT_QUERIES = (
    "semiconductor OR chip OR foundry",
    '"optical module" OR CPO OR "800G" OR "data center"',
    '"humanoid robot" OR robotics OR actuator',
    '"rare earth" OR copper OR tungsten OR antimony',
)


def collect_theme_events(
    *,
    rss_urls: list[str] | None = None,
    gdelt_queries: list[str] | None = None,
    max_items: int = 80,
    timeout: int = 8,
) -> list[dict[str, Any]]:
    urls = rss_urls if rss_urls is not None else _env_csv("THEME_RADAR_RSS_URLS")
    queries = gdelt_queries if gdelt_queries is not None else _default_gdelt_queries()
    events = _collect_rss_events(urls, timeout=timeout)
    events.extend(_collect_gdelt_events(queries, timeout=timeout, per_query=max(max_items // 4, 5)))
    return _dedupe_events(events)[:max_items]


def _default_gdelt_queries() -> list[str]:
    if env_flag("THEME_RADAR_GDELT_DISABLED"):
        return []
    return _env_csv("THEME_RADAR_GDELT_QUERIES") or list(DEFAULT_GDELT_QUERIES)


def _env_csv(name: str) -> list[str]:
    raw = os.getenv(name, "")
    return [part.strip() for part in raw.split(",") if part.strip()]


def _collect_rss_events(urls: list[str], *, timeout: int) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for url in urls:
        try:
            resp = requests.get(url, timeout=timeout, headers={"User-Agent": "WyckoffThemeRadar/1.0"})
            resp.raise_for_status()
            events.extend(_parse_rss(resp.content, source=url))
        except Exception:
            continue
    return events


def _parse_rss(payload: bytes, *, source: str) -> list[dict[str, Any]]:
    root = ET.fromstring(payload)
    entries = root.findall(".//item") or root.findall("{http://www.w3.org/2005/Atom}entry")
    return [_normalize_rss_entry(entry, source=source) for entry in entries]


def _normalize_rss_entry(entry: ET.Element, *, source: str) -> dict[str, Any]:
    title = _entry_text(entry, "title")
    summary = _entry_text(entry, "description") or _entry_text(entry, "summary")
    url = _entry_text(entry, "link")
    event = {
        "title": title,
        "summary": summary,
        "url": url or source,
        "source": source,
        "published_at": _published_at(_entry_text(entry, "pubDate") or _entry_text(entry, "updated")),
    }
    event["themes"] = infer_event_themes(event)
    return event


def _entry_text(entry: ET.Element, tag: str) -> str:
    node = entry.find(tag)
    if node is None:
        node = entry.find(f"{{http://www.w3.org/2005/Atom}}{tag}")
    if node is not None and node.text:
        return node.text.strip()
    if tag == "link":
        atom = entry.find("{http://www.w3.org/2005/Atom}link")
        return str(atom.get("href", "")).strip() if atom is not None else ""
    return ""


def _collect_gdelt_events(queries: list[str], *, timeout: int, per_query: int) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for query in queries:
        try:
            params = {"query": query, "mode": "artlist", "format": "json", "maxrecords": per_query, "sort": "datedesc"}
            resp = requests.get("https://api.gdeltproject.org/api/v2/doc/doc", params=params, timeout=timeout)
            resp.raise_for_status()
            events.extend(_normalize_gdelt_articles(resp.json().get("articles", []), query))
        except Exception:
            continue
    return events


def _normalize_gdelt_articles(articles: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    events = []
    for item in articles:
        event = {
            "title": str(item.get("title", "") or ""),
            "summary": str(item.get("seendate", "") or ""),
            "url": str(item.get("url", "") or ""),
            "source": str(item.get("domain", "") or "GDELT"),
            "published_at": str(item.get("seendate", "") or ""),
            "query": query,
        }
        event["themes"] = infer_event_themes(event)
        events.append(event)
    return events


def _dedupe_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped = []
    for event in events:
        key = str(event.get("url") or event.get("title") or "").strip()
        if key and key not in seen:
            seen.add(key)
            deduped.append(event)
    return deduped


def _published_at(value: str) -> str:
    if not value:
        return ""
    try:
        return parsedate_to_datetime(value).isoformat()
    except Exception:
        return value
