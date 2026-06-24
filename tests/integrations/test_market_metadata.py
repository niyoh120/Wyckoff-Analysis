from __future__ import annotations

import json

from integrations import market_metadata


def test_fetch_sector_map_reads_fresh_cache(tmp_path, monkeypatch) -> None:
    cache = tmp_path / "sector_map_cache.json"
    cache.write_text(json.dumps({"000001": "银行"}), encoding="utf-8")
    monkeypatch.setattr(market_metadata, "SECTOR_CACHE", cache)

    assert market_metadata.fetch_sector_map() == {"000001": "银行"}


def test_fetch_market_cap_map_normalizes_cached_values(tmp_path, monkeypatch) -> None:
    cache = tmp_path / "market_cap_cache.json"
    cache.write_text(json.dumps({"000001": "123.4"}), encoding="utf-8")
    monkeypatch.setattr(market_metadata, "MARKET_CAP_CACHE", cache)

    assert market_metadata.fetch_market_cap_map() == {"000001": 123.4}


def test_detect_theme_lines_uses_consecutive_recent_history(tmp_path, monkeypatch) -> None:
    history = tmp_path / "concept_heat_history.json"
    history.write_text(
        json.dumps(
            {
                "2026-06-20": {"AI算力": {}, "机器人": {}},
                "2026-06-19": {"AI算力": {}, "机器人": {}},
                "2026-06-18": {"AI算力": {}, "电力": {}},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(market_metadata, "CONCEPT_HEAT_HISTORY", history)

    assert market_metadata.detect_theme_lines(min_days=3) == ["AI算力"]
