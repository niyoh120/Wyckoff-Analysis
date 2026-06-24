from __future__ import annotations

import pytest

from tools.external_seeds import (
    ExternalSeedConfig,
    append_external_symbols,
    build_external_seed_rows,
    load_external_seed_config,
)


def test_external_seed_config_env_symbols_auto_enable(monkeypatch, tmp_path):
    profile = tmp_path / "profile.yml"
    profile.write_text("external_seeds:\n  enabled: false\n  max_symbols: 2\n", encoding="utf-8")
    monkeypatch.setenv("WYCKOFF_CONFIG_PATH", str(profile))
    monkeypatch.setenv("FUNNEL_EXTERNAL_SEED_SYMBOLS", "000001, bad, 000002, 000003")

    cfg = load_external_seed_config()

    assert cfg.enabled is True
    assert cfg.symbols == ("000001", "000002")
    assert cfg.max_symbols == 2


def test_append_external_symbols_preserves_order():
    cfg = ExternalSeedConfig(enabled=True, symbols=("000002", "000003"))

    merged, added = append_external_symbols(["000001", "000002"], cfg)

    assert merged == ["000001", "000002", "000003"]
    assert added == 1


def test_external_seed_rows_track_status_and_expiry():
    cfg = ExternalSeedConfig(
        enabled=True,
        source="ta",
        symbols=("000001", "000002", "000003"),
        watch_ttl_days=7,
    )

    rows = build_external_seed_rows(
        cfg,
        "2026-06-13",
        l1_codes=["000001", "000002"],
        l2_codes=["000002"],
        l4_triggers={"spring": [("000001", 2.0)]},
        name_map={"000001": "平安银行"},
        sector_map={"000001": "银行"},
    )

    by_code = {row["code"]: row for row in rows}
    assert by_code["000001"]["watch_status"] == "L4_CONFIRMED"
    assert by_code["000001"]["l4_trigger_tags"] == ["spring"]
    assert by_code["000002"]["watch_status"] == "PASSED_L2"
    assert by_code["000003"]["watch_status"] == "REJECTED_L1"
    assert {row["expires_at"] for row in rows} == {"2026-06-20"}


def test_external_seed_upsert_rejects_cli_context(monkeypatch):
    from integrations import supabase_external_seeds

    monkeypatch.delenv("WYCKOFF_WRITE_CONTEXT", raising=False)
    monkeypatch.setattr(supabase_external_seeds, "is_admin_configured", lambda: True)

    with pytest.raises(PermissionError, match="server_job"):
        supabase_external_seeds.upsert_external_seed_observations([{"code": "000001"}])


def test_external_seed_signal_rows_skip_already_selected():
    from workflows.daily_signal_observations import build_external_seed_signal_rows

    rows = build_external_seed_signal_rows(
        {
            "selected_for_ai": ["000001"],
            "metrics": {
                "external_seed_source": "ta",
                "external_seed_l4_triggers": {"spring": [("000001", 1.0), ("000002", 2.0)]},
            },
            "name_map": {"000002": "万科A"},
        },
        "NEUTRAL",
        trade_date="2026-06-13",
    )

    assert [row["code"] for row in rows] == ["000002"]
    assert rows[0]["source"] == "external_seed:ta"
    assert rows[0]["selection_mode"] == "external_seed_shadow"
