from __future__ import annotations

import pytest


def test_attribution_report_no_write_prefers_user_client(monkeypatch):
    import workflows.strategy_attribution_report as report

    marker = object()
    monkeypatch.setattr(report, "create_user_read_client", lambda: marker)

    def fail_admin():
        raise AssertionError("admin client should not be used for no-write reports")

    monkeypatch.setattr(report, "create_admin_client", fail_admin)

    assert report.create_report_client(no_write=True) is marker


def test_attribution_report_no_write_falls_back_to_read_client(monkeypatch):
    import workflows.strategy_attribution_report as report

    marker = object()
    monkeypatch.setattr(report, "create_user_read_client", lambda: None)
    monkeypatch.setattr(report, "create_read_client", lambda: marker)

    assert report.create_report_client(no_write=True) is marker


def test_attribution_report_write_requires_server_context(monkeypatch):
    import workflows.strategy_attribution_report as report

    monkeypatch.delenv("WYCKOFF_WRITE_CONTEXT", raising=False)
    with pytest.raises(PermissionError, match="server_job"):
        report.create_report_client(no_write=False)


def test_attribution_report_groups_candidate_shadow_grade():
    import workflows.strategy_attribution_stats as stats_mod

    observations = [
        {
            "id": 1,
            "features_json": {
                "candidate_shadow_score": {
                    "score": 88.5,
                    "grade": "S",
                    "positive_tags": ["quality_breakout"],
                    "negative_tags": [],
                },
                "data_lineage": {
                    "coverage_score": 95,
                    "coverage_grade": "strong",
                    "evidence_keys": ["daily_signal", "price_action", "intraday_tail"],
                },
            },
        },
        {
            "id": 2,
            "features_json": (
                '{"candidate_shadow_score":{"score":42,"grade":"D","negative_tags":["failed_breakout"]},'
                '"data_lineage":{"coverage_score":35,"coverage_grade":"thin","evidence_keys":["daily_signal"]}}'
            ),
        },
    ]
    outcomes = [
        {"observation_id": 1, "horizon_days": 5, "return_pct": 6.0, "max_drawdown_pct": -2.0},
        {"observation_id": 2, "horizon_days": 5, "return_pct": -5.0, "max_drawdown_pct": -7.0},
    ]

    joined = stats_mod.join_outcomes(outcomes, observations)
    stats = stats_mod.score_stats_json(joined, [5])

    assert joined[0]["candidate_shadow_score"] == 88.5
    assert joined[0]["candidate_shadow_grade"] == "S"
    assert joined[1]["candidate_shadow_grade"] == "D"
    assert stats["_candidate_shadow_grade"]["5"]["S"]["win_rate_pct"] == 100.0
    assert stats["_candidate_shadow_grade"]["5"]["D"]["big_loss_rate_pct"] == 100.0
    assert joined[0]["data_lineage_coverage_grade"] == "strong"
    assert joined[1]["data_lineage_evidence_keys"] == ["daily_signal"]
    assert stats["_data_lineage"]["coverage_grade"]["5"]["strong"]["win_rate_pct"] == 100.0
    assert stats["_data_lineage"]["coverage_grade"]["5"]["thin"]["big_loss_rate_pct"] == 100.0
    assert stats["_data_lineage"]["evidence_key"]["5"]["intraday_tail"]["avg_return_pct"] == 6.0
    assert stats["_data_lineage"]["coverage_summary"]["5"]["avg_coverage_score"] == 65.0
