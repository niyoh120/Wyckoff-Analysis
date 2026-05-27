from __future__ import annotations


def test_run_theme_radar_uses_full_concept_heat(monkeypatch) -> None:
    from scripts import theme_radar_job as mod

    captured: dict = {}
    metrics = {
        "end_trade_date": "2026-05-27",
        "concept_heat": [{"name": "top20"}],
        "concept_heat_full": [{"name": "full"}],
        "all_df_map": {},
        "_debug": {},
    }
    monkeypatch.setattr(mod, "run_funnel_job", lambda include_debug_context: ({}, metrics))
    monkeypatch.setattr(mod, "_load_concept_history", lambda: {})
    monkeypatch.setattr(mod, "build_theme_radar_snapshot", lambda **kwargs: captured.update(kwargs) or {})

    mod.run_theme_radar(with_news=False, persist=False)

    assert captured["concept_heat"] == [{"name": "full"}]
