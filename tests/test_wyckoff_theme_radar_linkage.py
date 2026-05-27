from __future__ import annotations


def test_theme_bonus_promotes_formal_l4_candidate(monkeypatch) -> None:
    from scripts import wyckoff_funnel as mod

    monkeypatch.setattr(mod, "FUNNEL_THEME_RADAR_PROMOTE_CAP", 6)
    selected: list[str] = []
    trend_selected: list[str] = []
    accum_selected: list[str] = []
    score_map: dict[str, float] = {}

    added = mod._promote_theme_l4_for_ai(
        selected,
        trend_selected,
        accum_selected,
        {"000001"},
        {"000001": 12.0},
        {"000001": 19.0},
        {"000001": ["sos"]},
        score_map,
    )

    assert added == 1
    assert selected == ["000001"]
    assert trend_selected == ["000001"]
    assert accum_selected == []
    assert score_map["000001"] == 19.0


def test_theme_report_fields_are_empty_for_non_strategic_code() -> None:
    from scripts import wyckoff_funnel as mod

    fields = mod._theme_report_fields("000002", {"000001": {"theme": "芯片半导体"}}, {"000001": 9.0})

    assert fields == {
        "strategic_theme": "",
        "strategic_theme_score": 0.0,
        "strategic_stock_score": 0.0,
        "strategic_theme_state": "",
        "strategic_theme_bonus": 0.0,
    }


def test_strategic_bypass_seed_codes_respects_l1_l2_and_scores(monkeypatch) -> None:
    from scripts import wyckoff_funnel as mod

    monkeypatch.setattr(mod, "FUNNEL_STRATEGIC_L2_BYPASS_ENABLED", True)
    monkeypatch.setattr(mod, "FUNNEL_STRATEGIC_L2_BYPASS_MIN_THEME_SCORE", 0.45)
    monkeypatch.setattr(mod, "FUNNEL_STRATEGIC_L2_BYPASS_MIN_STOCK_SCORE", 0.55)

    seeds = mod._strategic_bypass_seed_codes(
        ["000001", "000002", "000003", "000004"],
        ["000002"],
        {
            "000001": {"theme_score": 0.60, "stock_score": 0.70, "state": "observe"},
            "000002": {"theme_score": 0.80, "stock_score": 0.90, "state": "confirmed"},
            "000003": {"theme_score": 0.60, "stock_score": 0.20, "state": "observe"},
            "000004": {"theme_score": 0.80, "stock_score": 0.90, "state": "overheated"},
        },
    )

    assert seeds == ["000001"]


def test_l2_bypass_promotion_can_force_accum_track() -> None:
    from scripts import wyckoff_funnel as mod

    selected: list[str] = []
    trend_selected: list[str] = []
    accum_selected: list[str] = []

    added = mod._promote_l2_bypass_for_ai(
        selected,
        trend_selected,
        accum_selected,
        ["000001"],
        {"000001": 8.0},
        {"000001": []},
        {},
        enabled=True,
        cap=3,
        accum_codes={"000001"},
    )

    assert added == 1
    assert selected == ["000001"]
    assert trend_selected == []
    assert accum_selected == ["000001"]


def test_linked_theme_radar_falls_back_when_loader_fails(monkeypatch) -> None:
    from scripts import wyckoff_funnel as mod

    monkeypatch.setattr(mod, "FUNNEL_THEME_RADAR_LINK_ENABLED", True)

    import integrations.theme_radar_storage as storage

    monkeypatch.setattr(
        storage, "load_latest_theme_radar_snapshot", lambda: (_ for _ in ()).throw(RuntimeError("down"))
    )

    snapshot, source = mod._resolve_linked_theme_radar({"trade_date": "2026-05-27"}, "2026-05-27")

    assert source == "current"
    assert snapshot == {"trade_date": "2026-05-27"}


def test_linked_theme_radar_falls_back_when_persisted_snapshot_is_stale(monkeypatch) -> None:
    from scripts import wyckoff_funnel as mod

    monkeypatch.setattr(mod, "FUNNEL_THEME_RADAR_LINK_ENABLED", True)
    monkeypatch.setattr(mod, "FUNNEL_THEME_RADAR_MAX_AGE_DAYS", 3)

    import integrations.theme_radar_storage as storage

    monkeypatch.setattr(
        storage,
        "load_latest_theme_radar_snapshot",
        lambda: {"trade_date": "2026-05-01", "strategic_candidates": [{"code": "000001"}]},
    )

    snapshot, source = mod._resolve_linked_theme_radar({"trade_date": "2026-05-27"}, "2026-05-27")

    assert source == "current"
    assert snapshot == {"trade_date": "2026-05-27"}


def test_strategic_bypass_is_pluggable_when_disabled(monkeypatch) -> None:
    from scripts import wyckoff_funnel as mod

    monkeypatch.setattr(mod, "FUNNEL_STRATEGIC_L2_BYPASS_ENABLED", False)

    seeds = mod._strategic_bypass_seed_codes(
        ["000001"],
        [],
        {"000001": {"theme_score": 1.0, "stock_score": 1.0, "state": "confirmed"}},
    )

    assert seeds == []


def test_theme_radar_global_switch_disables_linkage(monkeypatch) -> None:
    from scripts import wyckoff_funnel as mod

    monkeypatch.setattr(mod, "FUNNEL_THEME_RADAR_ENABLED", False)
    monkeypatch.setattr(mod, "build_theme_radar_snapshot", lambda **_kwargs: (_ for _ in ()).throw(AssertionError))

    built = mod._safe_build_theme_radar(
        trade_date="2026-05-27",
        concept_heat=[],
        concept_map={},
        sector_map={},
        df_map={},
        name_map={},
    )
    linked, source = mod._resolve_linked_theme_radar(
        {"trade_date": "2026-05-27", "strategic_candidates": []}, "2026-05-27"
    )

    assert built == {"trade_date": "2026-05-27", "themes": [], "strategic_candidates": []}
    assert linked == {"trade_date": "2026-05-27", "themes": [], "strategic_candidates": []}
    assert source == "disabled"


def test_zero_theme_bonus_disables_theme_bonus_map(monkeypatch) -> None:
    from scripts import wyckoff_funnel as mod

    monkeypatch.setattr(mod, "FUNNEL_THEME_RADAR_BONUS_MAX", 0.0)

    assert mod._theme_bonus_map({"000001": {"theme_score": 1.0, "stock_score": 1.0}}) == {}
