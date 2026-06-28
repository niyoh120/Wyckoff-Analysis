from __future__ import annotations

import json
from argparse import Namespace
from datetime import date

from workflows import web_background_job as workflow


def test_load_payload_accepts_only_dict_json() -> None:
    assert workflow._load_payload('{"job": "x"}') == {"job": "x"}
    assert workflow._load_payload("[1, 2]") == {}
    assert workflow._load_payload("") == {}


def test_write_result_sanitizes_dates(tmp_path) -> None:
    target = tmp_path / "result.json"

    workflow._write_result(str(target), {"today": date(2026, 6, 23), "items": {1, 2}})

    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["today"] == "2026-06-23"
    assert sorted(payload["items"]) == [1, 2]


def test_run_web_background_job_writes_error_for_unknown_kind(tmp_path) -> None:
    target = tmp_path / "result.json"
    args = Namespace(job_kind="unknown", request_id="req1", payload_json='{"user_id":"u1"}', output=str(target))

    status = workflow.run_web_background_job(args)

    payload = json.loads(target.read_text(encoding="utf-8"))
    assert status == 1
    assert payload["status"] == "error"
    assert payload["request_id"] == "req1"
    assert "不支持的 job_kind" in payload["error"]


def test_run_web_background_job_runs_recommendation_event_eval(monkeypatch, tmp_path) -> None:
    captured = {}

    def fake_build(request):
        captured["request"] = request
        return {
            "metadata": {"market": request.market, "horizon_days": request.horizon_days},
            "summary": {"all": {"rows_ready": 1, "hit_rate_pct": 100.0}},
            "daily": [{"recommend_date": 20260601, "hit_rate_pct": 100.0}],
            "events": [],
            "persistence": {"applied": request.apply_labels, "rows_written": 1 if request.apply_labels else 0},
        }

    monkeypatch.setattr("workflows.recommendation_event_eval.build_recommendation_event_eval", fake_build)
    target = tmp_path / "result.json"
    args = Namespace(
        job_kind="recommendation_event_eval",
        request_id="req2",
        payload_json='{"market":"cn","horizon_days":5,"target_pct":10,"max_dates":7,"top_k":[1,3],"apply_labels":true}',
        output=str(target),
    )

    status = workflow.run_web_background_job(args)

    payload = json.loads(target.read_text(encoding="utf-8"))
    assert status == 0
    assert payload["status"] == "success"
    assert payload["job_kind"] == "recommendation_event_eval"
    assert payload["summary"]["all"]["hit_rate_pct"] == 100.0
    assert payload["persistence"]["applied"] is True
    assert captured["request"].max_dates == 7
    assert captured["request"].top_k == (1, 3)
    assert captured["request"].apply_labels is True
