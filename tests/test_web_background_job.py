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
