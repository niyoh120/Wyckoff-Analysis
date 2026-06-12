from __future__ import annotations

import argparse

import pandas as pd
import pytest

from core.dynamic_policy import build_signal_weight_map, filter_triggers_by_registry, resolve_dynamic_candidate_policy
from core.signal_confirmation import score_springboard_abc
from core.signal_feedback import build_signal_observations, build_signal_registry_updates, summarize_signal_health
from scripts.signal_feedback_job import _default_registry_horizon, _outcome_rows


class _FailingUpsertQuery:
    def upsert(self, _rows: list[dict], *, on_conflict: str):
        return self

    def execute(self):
        raise RuntimeError("db down")


class _FailingUpsertClient:
    def table(self, _name: str):
        return _FailingUpsertQuery()


class _CapturingUpsertQuery:
    def __init__(self, client):
        self.client = client

    def upsert(self, rows: list[dict], *, on_conflict: str):
        self.client.rows = rows
        self.client.conflict = on_conflict
        return self

    def execute(self):
        return None


class _CapturingUpsertClient:
    def __init__(self):
        self.rows: list[dict] = []
        self.conflict = ""

    def table(self, name: str):
        self.table_name = name
        return _CapturingUpsertQuery(self)


def test_build_signal_observations_marks_selection_and_source():
    rows = build_signal_observations(
        "2026-05-25",
        {"sos": [("000001", 12.5)], "spring": [("000002", 9.0)]},
        regime="risk_on",
        selected_for_ai=["000001"],
        ai_recommended=["000001"],
        name_map={"000001": "平安银行"},
        sector_map={"000001": "银行"},
        score_map={"000001": 88},
        latest_close_map={"000001": 10.5},
        source_map={"000002": "l2_bypass"},
        springboard_map={
            "sos:000001": {
                "springboard_grade": "A+B",
                "springboard_met_count": 2,
                "springboard_a": True,
                "springboard_b": True,
                "springboard_c": False,
                "springboard_support": 10.1,
                "springboard_touch_count": 1,
                "springboard_evidence": {"a_hits": [{"date": "2026-05-24"}]},
            },
            "spring:000002": {
                "springboard_grade": "C",
                "springboard_met_count": 1,
                "springboard_a": False,
                "springboard_b": False,
                "springboard_c": True,
                "springboard_support": 8.8,
                "springboard_touch_count": 3,
                "springboard_evidence": {"c_support": {"touch_dates": ["2026-05-20"]}},
            },
        },
    )

    first = rows[0]
    second = rows[1]
    assert first["signal_type"] == "sos"
    assert first["track"] == "Trend"
    assert first["selected_for_ai"] is True
    assert first["ai_recommended"] is True
    assert first["entry_price"] == 10.5
    assert first["springboard_grade"] == "A+B"
    assert first["springboard_met_count"] == 2
    assert first["springboard_a"] is True
    assert first["springboard_evidence"]["a_hits"][0]["date"] == "2026-05-24"
    assert second["track"] == "Accum"
    assert second["source"] == "l2_bypass"
    assert second["springboard_grade"] == "C"
    assert second["springboard_c"] is True


def test_score_springboard_abc_returns_persistable_metadata():
    dates = pd.date_range("2026-05-01", periods=25, freq="D")
    df = pd.DataFrame(
        {
            "date": dates,
            "open": [10.0] * 25,
            "high": [11.0] * 25,
            "low": [10.0] * 25,
            "close": [10.5] * 25,
            "volume": [100.0] * 25,
        }
    )
    df.loc[22, ["close", "volume"]] = [10.8, 50.0]
    df.loc[24, ["close", "volume"]] = [10.9, 220.0]

    result = score_springboard_abc(df, "spring")

    assert result["a"] is True
    assert result["b"] is True
    assert result["c"] is True
    assert result["grade"] == "A+B+C"
    assert result["touch_count"] >= 2
    assert result["evidence"]["b_last"]["date"] == "2026-05-25"


def test_signal_feedback_upsert_errors_propagate(monkeypatch):
    from integrations import supabase_signal_feedback

    closed = []
    monkeypatch.setenv("WYCKOFF_WRITE_CONTEXT", "server_job")
    monkeypatch.setattr(supabase_signal_feedback, "_configured", lambda: True)
    monkeypatch.setattr(supabase_signal_feedback, "_admin", _FailingUpsertClient)
    monkeypatch.setattr(supabase_signal_feedback, "_close", closed.append)

    with pytest.raises(RuntimeError, match="db down"):
        supabase_signal_feedback.upsert_signal_outcomes([{"observation_id": 1, "horizon_days": 1}])

    assert len(closed) == 1


def test_signal_feedback_upsert_rejects_cli_context(monkeypatch):
    from integrations import supabase_signal_feedback

    monkeypatch.delenv("WYCKOFF_WRITE_CONTEXT", raising=False)
    monkeypatch.setattr(supabase_signal_feedback, "_configured", lambda: True)

    with pytest.raises(PermissionError, match="server_job"):
        supabase_signal_feedback.upsert_signal_outcomes([{"observation_id": 1, "horizon_days": 1}])


def test_signal_observations_conflict_keeps_daily_tags(monkeypatch):
    from integrations import supabase_signal_feedback

    client = _CapturingUpsertClient()
    monkeypatch.setenv("WYCKOFF_WRITE_CONTEXT", "server_job")
    monkeypatch.setattr(supabase_signal_feedback, "_configured", lambda: True)
    monkeypatch.setattr(supabase_signal_feedback, "_admin", lambda: client)
    monkeypatch.setattr(supabase_signal_feedback, "_close", lambda _client: None)

    rows = [
        {"market": "cn", "trade_date": "2026-06-10", "code": "000001", "signal_type": "spring"},
        {"market": "cn", "trade_date": "2026-06-11", "code": "000001", "signal_type": "lps"},
    ]

    assert supabase_signal_feedback.upsert_signal_observations(rows) == 2
    assert client.conflict == "market,trade_date,code,signal_type"
    assert [row["trade_date"] for row in client.rows] == ["2026-06-10", "2026-06-11"]


def test_summarize_signal_health_classifies_watch_and_all_regime():
    outcomes = []
    for idx in range(20):
        outcomes.append(
            {
                "signal_type": "spring",
                "track": "Accum",
                "regime": "RISK_OFF",
                "horizon_days": 10,
                "status": "done",
                "return_pct": -1 if idx < 14 else 2,
                "max_drawdown_pct": -3,
            }
        )

    rows = summarize_signal_health(outcomes, as_of_date="2026-05-25", min_samples=20)
    by_regime = {row["regime"]: row for row in rows}

    assert set(by_regime) == {"ALL", "RISK_OFF"}
    assert by_regime["ALL"]["health_state"] == "DECAYED"
    assert by_regime["ALL"]["weight_multiplier"] == 0.4
    assert by_regime["RISK_OFF"]["sample_count"] == 20


def test_dynamic_policy_shifts_quota_toward_healthier_track():
    base = {
        "quota_family": "NEUTRAL",
        "total_cap": 10,
        "requested_trend_quota": 5,
        "requested_accum_quota": 5,
        "trend_quota": 5,
        "accum_quota": 5,
    }

    policy = resolve_dynamic_candidate_policy(base, {"sos": 1.0, "spring": 0.4})

    assert policy["quota_family"] == "NEUTRAL+DYNAMIC"
    assert policy["trend_quota"] > policy["accum_quota"]


def test_dynamic_policy_uses_configured_feedback_horizon(monkeypatch):
    monkeypatch.setenv("FUNNEL_DYNAMIC_POLICY_HORIZON", "5")
    weights = build_signal_weight_map(
        [
            {"as_of_date": "2026-06-10", "horizon_days": 10, "signal_type": "lps", "weight_multiplier": 1.2},
            {"as_of_date": "2026-06-10", "horizon_days": 5, "signal_type": "lps", "weight_multiplier": 0.4},
        ]
    )

    assert weights["lps"] == 0.4


def test_signal_feedback_registry_horizon_defaults_to_five(monkeypatch):
    monkeypatch.delenv("SIGNAL_REGISTRY_HORIZON", raising=False)

    assert _default_registry_horizon() == 5


def test_registry_retires_after_repeated_decay():
    updates = build_signal_registry_updates(
        [
            {
                "signal_type": "spring",
                "track": "Accum",
                "regime": "ALL",
                "horizon_days": 10,
                "health_state": "DECAYED",
                "weight_multiplier": 0.4,
            }
        ],
        registry_rows=[{"signal_type": "spring", "status": "WATCH"}],
    )

    assert updates[0]["status"] == "RETIRED"


def test_filter_triggers_by_registry_blocks_experimental_signal():
    filtered = filter_triggers_by_registry(
        {"sos": [("000001", 1.0)], "spring": [("000002", 1.0)]},
        [{"signal_type": "spring", "status": "EXPERIMENTAL"}],
    )

    assert "sos" in filtered
    assert "spring" not in filtered


def test_shadow_selection_diff_preserves_shadow_order():
    from scripts.wyckoff_funnel import _selection_diff

    added, removed = _selection_diff(["000001", "000002"], ["000002", "000003"])

    assert added == ["000003"]
    assert removed == ["000001"]


def test_attach_shadow_policy_preserves_base_policy():
    from scripts.wyckoff_funnel import _attach_shadow_policy

    base = {"trend_quota": 8, "accum_quota": 4, "quota_family": "FULL_FORMAL_L4"}
    shadow = {"trend_quota": 3, "accum_quota": 5, "quota_family": "RISK_ON+DYNAMIC"}

    _attach_shadow_policy(
        base,
        {
            "mode": "shadow",
            "policy": shadow,
            "weights": {"sos": 0.8},
            "registry": [{"signal_type": "sos"}],
            "health": [{"signal_type": "sos"}],
        },
    )

    assert base["trend_quota"] == 8
    assert base["accum_quota"] == 4
    assert base["_dynamic_mode"] == "shadow"
    assert base["_shadow_policy"] == shadow
    assert base["_signal_weights"] == {"sos": 0.8}


def test_signal_feedback_job_builds_outcome_rows():
    obs = {
        "id": 1,
        "market": "cn",
        "trade_date": "2024-01-02",
        "code": "000001",
        "signal_type": "sos",
        "track": "Trend",
        "regime": "NEUTRAL",
        "entry_price": 11,
    }
    hist = pd.DataFrame(
        {
            "date": pd.bdate_range("2024-01-01", periods=4).astype(str),
            "close": [10, 11, 12, 13],
            "low": [9, 10.5, 11.5, 12],
        }
    )

    rows = _outcome_rows(obs, hist, argparse.Namespace(horizons=(1,)).horizons)

    assert rows[0]["observation_id"] == 1
    assert rows[0]["horizon_days"] == 1
    assert rows[0]["status"] == "done"
    assert round(rows[0]["return_pct"], 2) == 9.09
