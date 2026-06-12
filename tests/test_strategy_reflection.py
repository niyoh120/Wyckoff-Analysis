from __future__ import annotations

import argparse


def test_build_strategy_reflection_and_candidate():
    from core.strategy_reflection import build_policy_candidate, build_strategy_reflection

    outcomes = [
        {"track": "Trend", "regime": "RISK_ON", "horizon_days": 5, "status": "done", "return_pct": 0.5},
        {"track": "Accum", "regime": "RISK_ON", "horizon_days": 5, "status": "done", "return_pct": 3.0},
        {"track": "Accum", "regime": "RISK_ON", "horizon_days": 5, "status": "done", "return_pct": -1.0},
    ]
    shadow_runs = [{"diff_added": ["000001"], "diff_removed": ["000002", "000003"]}]

    reflection = build_strategy_reflection(outcomes, shadow_runs, market="cn", as_of_date="2026-06-12")
    candidate = build_policy_candidate(reflection)

    assert reflection["status"] == "SHADOW"
    assert reflection["summary"]["preferred_track"] == "Accum"
    assert reflection["summary"]["shadow"]["avg_removed"] == 2.0
    assert candidate is not None
    assert candidate["status"] == "READY_FOR_REVIEW"
    assert candidate["candidate_policy"]["auto_promote"] is False


def test_strategy_reflection_job_dry_run_payload(monkeypatch):
    from scripts import strategy_reflection_job as job

    args = argparse.Namespace(
        market="cn",
        as_of_date="2026-06-12",
        horizon_days=5,
        outcome_days=180,
        shadow_days=30,
        limit=100,
    )
    monkeypatch.setattr(
        job,
        "load_recent_signal_outcomes",
        lambda *_args: [{"track": "Trend", "regime": "ALL", "horizon_days": 5, "status": "done", "return_pct": 2}],
    )
    monkeypatch.setattr(job, "load_policy_shadow_runs", lambda *_args: [{"diff_added": [], "diff_removed": []}])

    reflection, candidate = job._build_payloads(args)

    assert reflection["as_of_date"] == "2026-06-12"
    assert reflection["summary"]["preferred_track"] == "Trend"
    assert candidate is not None
    assert candidate["status"] == "READY_FOR_REVIEW"
