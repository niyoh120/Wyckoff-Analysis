from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

from core.tail_buy.models import TailBuyCandidate
from workflows import tail_buy_intraday_job as job
from workflows.tail_buy_utils import current_time


def _candidate(code: str, score: float = 0.0) -> TailBuyCandidate:
    return TailBuyCandidate(
        code=code,
        name=code,
        signal_date="2026-06-22",
        status="confirmed",
        signal_type="sos",
        signal_score=70.0,
        rule_score=score,
    )


def test_validate_runtime_config_requires_tickflow_and_feishu(monkeypatch) -> None:
    logs: list[str] = []
    monkeypatch.setattr(job, "log_line", lambda message, *_args, **_kwargs: logs.append(message))

    missing_tickflow = SimpleNamespace(tickflow_api_key="", feishu_webhook="feishu", logs_path="")
    missing_feishu = SimpleNamespace(tickflow_api_key="tf", feishu_webhook="", logs_path="")

    assert job.validate_tail_buy_runtime_config(missing_tickflow) == 1
    assert job.validate_tail_buy_runtime_config(missing_feishu) == 1
    assert any("TICKFLOW_API_KEY" in item for item in logs)
    assert any("FEISHU_WEBHOOK_URL" in item for item in logs)


def test_candidate_flow_empty_pool_skips_rule_and_llm(monkeypatch) -> None:
    logs: list[str] = []
    monkeypatch.setattr(job, "log_line", lambda message, *_args, **_kwargs: logs.append(message))

    result = job.run_tail_buy_candidate_flow(
        [],
        tickflow_client=object(),
        config=SimpleNamespace(logs_path=""),
    )

    assert result.merged == []
    assert result.llm_total == 0
    assert result.llm_success == 0
    assert logs == ["候选池为空：本轮仅输出持仓动作建议。"]


def test_single_rule_scan_marks_deferred_candidates(monkeypatch) -> None:
    scanned = [_candidate("000001", score=80)]
    deferred = _candidate("000002")
    monkeypatch.setattr(job, "log_line", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(job, "run_rule_scan", lambda candidates, **_kwargs: scanned[: len(candidates)])

    result = job.run_tail_buy_single_rule_scan(
        [scanned[0], deferred],
        tickflow_client=object(),
        config=SimpleNamespace(
            intraday_limit_per_min=1,
            max_over_limit_symbols=0,
            force_over_limit=False,
            logs_path="",
            style="auto",
            fetch_concurrency=1,
            strategy_config=object(),
            deadline_at=current_time() + timedelta(minutes=5),
        ),
    )

    assert [item.code for item in result] == ["000001", "000002"]
    assert "限流保护" in str(deferred.fetch_error)
    assert deferred.rule_reasons == [deferred.fetch_error]
