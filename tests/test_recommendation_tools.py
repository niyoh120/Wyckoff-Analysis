from __future__ import annotations

from agents.recommendation_tools import evaluate_recommendation_events


def test_evaluate_recommendation_events_returns_policy_selection(monkeypatch):
    captured = {}

    def fake_build(request):
        captured["request"] = request
        return {
            "metadata": {"market": request.market, "horizon_days": request.horizon_days},
            "summary": {
                "all": {"rows_ready": 12, "rows_total": 20, "hit_rate_pct": 60.0},
                "ranking_decision": {
                    "status": "candidate",
                    "recommended_strategy": "candidate_shadow_then_score",
                    "recommended_top_k": 1,
                    "reason": "candidate_shadow_then_score top1 passed lift and risk gates",
                },
            },
            "policy_selection": {
                "selection_strategy": "candidate_shadow_then_score",
                "recommend_date": 20260601,
                "picks": [{"code": "300750", "name": "宁德时代"}],
            },
            "daily": [{"recommend_date": 20260601, "hit_rate_pct": 100.0}],
            "events": [],
        }

    monkeypatch.setattr("workflows.recommendation_event_eval.build_recommendation_event_eval", fake_build)

    result = evaluate_recommendation_events(market="cn", top_k="1,3")

    assert result["ok"] is True
    assert result["job_kind"] == "recommendation_event_eval"
    assert result["policy_selection"]["picks"][0]["code"] == "300750"
    assert "ranking_decision=candidate" in result["result_summary"]
    assert "最新候选(20260601, candidate_shadow_then_score): 300750 宁德时代" in result["result_summary"]
    assert captured["request"].top_k == (1, 3)


def test_evaluate_recommendation_events_surfaces_config_error(monkeypatch):
    def fake_build(_request):
        raise ValueError("TICKFLOW_API_KEY 未配置")

    monkeypatch.setattr("workflows.recommendation_event_eval.build_recommendation_event_eval", fake_build)

    result = evaluate_recommendation_events()

    assert "TICKFLOW_API_KEY 未配置" in result["error"]
    assert "SUPABASE_URL" in result["hint"]
