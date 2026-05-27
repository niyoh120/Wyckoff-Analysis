from __future__ import annotations

import argparse

import pandas as pd
import pytest

from core.dynamic_policy import filter_triggers_by_registry, resolve_dynamic_candidate_policy
from core.signal_feedback import build_signal_observations, build_signal_registry_updates, summarize_signal_health
from scripts.signal_feedback_job import _outcome_rows


class _FailingUpsertQuery:
    def upsert(self, _rows: list[dict], *, on_conflict: str):
        return self

    def execute(self):
        raise RuntimeError("db down")


class _FailingUpsertClient:
    def table(self, _name: str):
        return _FailingUpsertQuery()


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
    )

    first = rows[0]
    second = rows[1]
    assert first["signal_type"] == "sos"
    assert first["track"] == "Trend"
    assert first["selected_for_ai"] is True
    assert first["ai_recommended"] is True
    assert first["entry_price"] == 10.5
    assert second["track"] == "Accum"
    assert second["source"] == "l2_bypass"


def test_signal_feedback_upsert_errors_propagate(monkeypatch):
    from integrations import supabase_signal_feedback

    closed = []
    monkeypatch.setattr(supabase_signal_feedback, "_configured", lambda: True)
    monkeypatch.setattr(supabase_signal_feedback, "_admin", _FailingUpsertClient)
    monkeypatch.setattr(supabase_signal_feedback, "_close", closed.append)

    with pytest.raises(RuntimeError, match="db down"):
        supabase_signal_feedback.upsert_signal_outcomes([{"observation_id": 1, "horizon_days": 1}])

    assert len(closed) == 1


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
