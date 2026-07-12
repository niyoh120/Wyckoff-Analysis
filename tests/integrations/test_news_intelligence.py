from __future__ import annotations

import json

from integrations import news_intelligence as intel


class _Response:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self) -> bytes:
        return json.dumps({"items": [{"title": "新闻", "url": "https://example.com/news"}]}).encode()


def test_refresh_intelligence_pool_respects_disabled_setting(monkeypatch):
    monkeypatch.setenv("NEWS_INTEL_AUTO_FETCH_ENABLED", "false")
    monkeypatch.setattr(
        intel.urllib.request, "urlopen", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError())
    )

    intel.refresh_intelligence_pool()


def test_refresh_intelligence_pool_fetches_and_obeys_cooldown(monkeypatch):
    calls = []
    saved = []
    monkeypatch.setenv("NEWS_INTEL_AUTO_FETCH_ENABLED", "true")
    monkeypatch.setattr(intel, "DEFAULT_NEWSNOW_SOURCES", ["source-a"])
    monkeypatch.setattr(intel.time, "monotonic", lambda: 1000.0)
    monkeypatch.setattr(intel.urllib.request, "urlopen", lambda *_args, **_kwargs: calls.append(1) or _Response())
    monkeypatch.setattr(intel, "save_intelligence_items", lambda items: saved.extend(items) or len(items))
    monkeypatch.setattr(intel, "_last_fetch_time", 0.0)

    intel.refresh_intelligence_pool()
    intel.refresh_intelligence_pool()

    assert len(calls) == 1
    assert saved[0]["source"] == "source-a"


def test_refresh_intelligence_pool_is_fail_open(monkeypatch):
    monkeypatch.setenv("NEWS_INTEL_AUTO_FETCH_ENABLED", "true")
    monkeypatch.setattr(intel, "DEFAULT_NEWSNOW_SOURCES", ["broken"])
    monkeypatch.setattr(intel, "_last_fetch_time", 0.0)
    monkeypatch.setattr(
        intel.urllib.request, "urlopen", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("down"))
    )

    intel.refresh_intelligence_pool()
