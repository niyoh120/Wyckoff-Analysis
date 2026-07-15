from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

from core.tail_buy.models import TailBuyCandidate
from workflows import tail_buy_intraday_job as job
from workflows.strategy_attribution_policy import AttributionPolicySnapshot
from workflows.tail_buy_market_repair import apply_base_market_regime, apply_intraday_market_mode
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


class TestPrefilterUnconfirmed:
    """_prefilter_unconfirmed 在 confirmed_only_buy=True 时跳过未确认候选。"""

    def _config(self, confirmed_only_buy: bool):
        return SimpleNamespace(
            logs_path="",
            strategy_config=SimpleNamespace(confirmed_only_buy=confirmed_only_buy),
        )

    def _candidate(self, code: str, *, status: str, signal_type: str = "sos"):
        return TailBuyCandidate(
            code=code,
            name=code,
            signal_date="2026-06-22",
            status=status,
            signal_type=signal_type,
            signal_score=70.0,
        )

    def test_confirmed_only_buy_filters_unconfirmed(self, monkeypatch):
        logs: list[str] = []
        monkeypatch.setattr(job, "log_line", lambda msg, *_a, **_kw: logs.append(msg))

        candidates = [
            self._candidate("000001", status="confirmed"),
            self._candidate("000002", status="pending"),
            self._candidate("000003", status="pending"),
        ]
        to_scan, deferred = job._prefilter_unconfirmed(candidates, self._config(True))

        assert [c.code for c in to_scan] == ["000001"]
        assert [c.code for c in deferred] == ["000002", "000003"]
        assert deferred[0].rule_decision == "WATCH"
        assert deferred[0].final_decision == "WATCH"
        assert "未二次确认" in deferred[0].rule_reasons[0]
        assert any("confirmed=1" in line for line in logs)

    def test_confirmed_only_buy_false_returns_all(self, monkeypatch):
        monkeypatch.setattr(job, "log_line", lambda *_a, **_kw: None)

        candidates = [
            self._candidate("000001", status="confirmed"),
            self._candidate("000002", status="pending"),
        ]
        to_scan, deferred = job._prefilter_unconfirmed(candidates, self._config(False))

        assert len(to_scan) == 2
        assert deferred == []

    def test_holding_always_scanned_even_if_pending(self, monkeypatch):
        monkeypatch.setattr(job, "log_line", lambda *_a, **_kw: None)

        candidates = [
            self._candidate("000001", status="pending", signal_type="holding"),
            self._candidate("000002", status="pending", signal_type="sos"),
        ]
        to_scan, deferred = job._prefilter_unconfirmed(candidates, self._config(True))

        assert [c.code for c in to_scan] == ["000001"]
        assert [c.code for c in deferred] == ["000002"]


def test_candidate_flow_applies_policy_weights_before_merge(monkeypatch) -> None:
    candidate = _candidate("000001", score=80)
    calls: dict[str, object] = {}

    monkeypatch.setattr(job, "run_tail_buy_rule_scan", lambda *_args, **_kwargs: [candidate])
    monkeypatch.setattr(
        job,
        "load_tail_buy_policy_snapshot",
        lambda _logs: AttributionPolicySnapshot(
            weights={"lps": 0.5},
            source="远端",
            report_date="2026-07-04",
            horizon="5",
            age_days=0,
            execution_policy="shadow",
            execution_scope="tail_buy_and_funnel_shadow",
            next_action="manual_review_dynamic_on",
            formal_dynamic_allowed=True,
        ),
    )

    def fake_adjust(scored, weights, *, policy_meta=None):
        calls["weights"] = weights
        calls["policy_meta"] = policy_meta
        scored[0].rule_score = 40.0
        return scored

    monkeypatch.setattr(job, "apply_policy_weight_adjustments", fake_adjust)
    monkeypatch.setattr(job, "merge_rule_and_llm", lambda scored, _llm, **_kwargs: scored)

    result = job.run_tail_buy_candidate_flow(
        [candidate],
        tickflow_client=object(),
        config=SimpleNamespace(
            logs_path="",
            llm_routes=[],
            style="auto",
            max_llm_symbols=5,
            llm_min_rule_score=60.0,
            llm_allowed_rule_decisions=("BUY", "WATCH"),
            llm_concurrency=1,
            deadline_at=current_time() + timedelta(minutes=5),
            strategy_config=SimpleNamespace(confirmed_only_buy=False),
        ),
    )

    assert calls["weights"] == {"lps": 0.5}
    assert calls["policy_meta"]["report_date"] == "2026-07-04"
    assert calls["policy_meta"]["execution_scope"] == "tail_buy_and_funnel_shadow"
    assert calls["policy_meta"]["next_action"] == "manual_review_dynamic_on"
    assert result.merged[0].rule_score == 40.0
    assert result.policy_weights == {"lps": 0.5}
    assert result.policy_weight_meta["source"] == "远端"
    assert result.policy_weight_meta["execution_policy"] == "shadow"
    assert result.policy_weight_meta["next_action"] == "manual_review_dynamic_on"
    assert result.llm_total == 0


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


def test_apply_intraday_repair_mode_only_overrides_weak_candidates() -> None:
    weak = _candidate("000001")
    weak.market_regime = "CRASH"
    neutral = _candidate("000002")
    neutral.market_regime = "NEUTRAL"

    changed = apply_intraday_market_mode([weak, neutral], mode="PANIC_REPAIR_INTRADAY")

    assert changed == 1
    assert weak.market_regime == "PANIC_REPAIR_INTRADAY"
    assert neutral.market_regime == "NEUTRAL"


def test_apply_base_market_regime_fills_missing_candidate_state() -> None:
    missing = _candidate("000001")
    existing = _candidate("000002")
    existing.market_regime = "NEUTRAL"

    changed = apply_base_market_regime([missing, existing], "UNKNOWN/NORMAL | 禁止新开仓")

    assert changed == 1
    assert missing.market_regime == "UNKNOWN"
    assert existing.market_regime == "NEUTRAL"


def test_auto_run_plan_uses_intraday_before_close(monkeypatch) -> None:
    monkeypatch.setattr(job, "resolve_tail_buy_trade_dates", lambda _logs: ("2026-06-26", "2026-06-29"))
    monkeypatch.setattr(job, "has_signal_pending_on_date", lambda *_args, **_kwargs: True)
    config = SimpleNamespace(
        mode="auto", started_at=datetime(2026, 6, 29, 14, 45, tzinfo=current_time().tzinfo), logs_path=""
    )

    plan = job.resolve_tail_buy_run_plan(config)

    assert plan.mode == "intraday"
    assert plan.target_signal_date == "2026-06-26"
    assert plan.include_holding_candidates is True
    assert plan.persist_results is True


def test_auto_run_plan_uses_post_close_when_today_result_exists(monkeypatch) -> None:
    monkeypatch.setattr(job, "resolve_tail_buy_trade_dates", lambda _logs: ("2026-06-26", "2026-06-29"))
    monkeypatch.setattr(job, "has_signal_pending_on_date", lambda *_args, **_kwargs: True)
    config = SimpleNamespace(
        mode="auto", started_at=datetime(2026, 6, 29, 17, 45, tzinfo=current_time().tzinfo), logs_path=""
    )

    plan = job.resolve_tail_buy_run_plan(config)

    assert plan.mode == "post_close_review"
    assert plan.target_signal_date == "2026-06-29"
    assert plan.strict_signal_date is True
    assert plan.include_holding_candidates is False
    assert plan.persist_results is False


def test_auto_run_plan_skips_post_close_without_today_result(monkeypatch) -> None:
    monkeypatch.setattr(job, "resolve_tail_buy_trade_dates", lambda _logs: ("2026-06-26", "2026-06-29"))
    monkeypatch.setattr(job, "has_signal_pending_on_date", lambda *_args, **_kwargs: False)
    config = SimpleNamespace(
        mode="auto", started_at=datetime(2026, 6, 29, 17, 45, tzinfo=current_time().tzinfo), logs_path=""
    )

    plan = job.resolve_tail_buy_run_plan(config)

    assert plan.mode == "post_close_review"
    assert plan.skip_reason


def test_tail_buy_delivery_succeeds_when_telegram_not_configured() -> None:
    config = SimpleNamespace(tg_bot_token="", tg_chat_id="")

    assert job._tail_buy_delivery_succeeded(config, feishu_ok=True, tg_ok=False) is True
