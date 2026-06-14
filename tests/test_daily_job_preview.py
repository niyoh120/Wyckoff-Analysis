from __future__ import annotations

import sys
from datetime import date


def test_preview_only_skips_persistence_and_keeps_llm_input_path(monkeypatch, tmp_path):
    import core.batch_report as batch_report
    import core.funnel_pipeline as funnel_pipeline
    import integrations.supabase_signal_pending as signal_pending
    import scripts.daily_job as daily_job

    captured: dict[str, object] = {}

    def forbidden_write(*_args, **_kwargs):
        raise AssertionError("preview-only job must not write persistence tables")

    def fake_run_funnel(webhook_url, *, notify=True, return_details=False):
        captured["step2_webhook"] = webhook_url
        captured["step2_notify"] = notify
        captured["step2_return_details"] = return_details
        return (
            True,
            [{"code": "000001", "name": "平安银行", "tag": "SOS"}],
            {"regime": "NEUTRAL"},
            {
                "triggers": {"sos": [("000002", 1.0)]},
                "all_df_map": {"000002": object()},
                "name_map": {"000002": "万科A"},
                "sector_map": {"000002": "房地产"},
            },
        )

    def fake_run_step2_5(*_args, dry_run=False, **_kwargs):
        captured["signal_dry_run"] = dry_run
        return [{"code": "000002", "name": "万科A", "tag": "pending confirmed"}]

    def fake_run_step3(symbols_info, webhook_url, *_args, **_kwargs):
        captured["step3_symbols"] = [item["code"] for item in symbols_info]
        captured["step3_webhook"] = webhook_url
        return True, "ok_preview", "# Step3 模型输入预演"

    monkeypatch.setenv("STEP3_SKIP_LLM", "1")
    monkeypatch.setenv("DAILY_JOB_SKIP_STEP4", "1")
    monkeypatch.setenv("DAILY_JOB_PREVIEW_ONLY", "1")
    monkeypatch.setenv("FEISHU_WEBHOOK_URL", "https://example.invalid/webhook")
    monkeypatch.setattr(sys, "argv", ["daily_job.py", "--logs", str(tmp_path / "preview.log")])
    monkeypatch.setattr(daily_job, "resolve_end_calendar_day", lambda: date(2026, 5, 31))
    monkeypatch.setattr(daily_job, "is_a_share_trading_day", lambda d: d == date(2026, 6, 1))
    monkeypatch.setattr(daily_job, "_latest_trade_date_str", lambda: "2026-05-19")
    monkeypatch.setattr(daily_job, "upsert_market_signal_daily", forbidden_write)
    monkeypatch.setattr(daily_job, "prepare_recommendation_payload", forbidden_write)
    monkeypatch.setattr(daily_job, "upsert_recommendation_payload", forbidden_write)
    monkeypatch.setattr(daily_job, "mark_ai_recommendations", forbidden_write)
    monkeypatch.setattr(daily_job, "_run_springboard_scoring", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(funnel_pipeline, "run_funnel", fake_run_funnel)
    monkeypatch.setattr(batch_report, "run_step3", fake_run_step3)
    monkeypatch.setattr(batch_report, "extract_operation_pool_codes", lambda **_kwargs: ["000001"])
    monkeypatch.setattr(signal_pending, "run_step2_5", fake_run_step2_5)

    assert daily_job.main() == 0
    assert captured["step2_webhook"] == ""
    assert captured["step2_notify"] is False
    assert captured["step2_return_details"] is True
    assert captured["signal_dry_run"] is True
    assert captured["step3_webhook"] == "https://example.invalid/webhook"
    assert captured["step3_symbols"] == ["000001", "000002"]


def test_non_trading_skip_message_allows_when_next_day_trades(monkeypatch):
    import scripts.daily_job as daily_job

    monkeypatch.setattr(daily_job, "is_a_share_trading_day", lambda d: d == date(2026, 6, 1))

    assert daily_job._non_trading_skip_message(date(2026, 5, 31)) is None


def test_non_trading_skip_message_skips_when_next_day_is_closed(monkeypatch):
    import scripts.daily_job as daily_job

    monkeypatch.setattr(daily_job, "is_a_share_trading_day", lambda _day: False)

    msg = daily_job._non_trading_skip_message(date(2026, 5, 29))

    assert msg == "📅 明日 2026-05-30 非 A 股交易日，任务跳过"


def test_non_trading_skip_message_skips_holiday_before_next_trade(monkeypatch):
    import scripts.daily_job as daily_job

    monkeypatch.setattr(daily_job, "is_a_share_trading_day", lambda d: d == date(2026, 6, 3))

    msg = daily_job._non_trading_skip_message(date(2026, 5, 30))

    assert msg == "📅 明日 2026-05-31 非 A 股交易日，任务跳过"


def test_step4_candidate_confirmation_gate_accepts_only_confirmed():
    import scripts.daily_job as daily_job

    assert daily_job._is_confirmed_step4_candidate({"tag": "SOS(确认)"})
    assert daily_job._is_confirmed_step4_candidate({"status": "confirmed"})
    assert not daily_job._is_confirmed_step4_candidate({"tag": "SOS（量价点火）"})


def test_signal_confirmation_dry_run_does_not_write(monkeypatch):
    import integrations.supabase_signal_pending as signal_pending

    writes: list[str] = []
    monkeypatch.setattr(signal_pending, "write_pending_signals", lambda *_args, **_kwargs: writes.append("insert"))
    monkeypatch.setattr(signal_pending, "load_pending_signals", lambda: [{"id": 1, "code": 1}])
    monkeypatch.setattr(
        signal_pending,
        "run_confirmation_cycle",
        lambda *_args, **_kwargs: ([{"id": 1, "status": "confirmed"}], [{"code": "000001"}]),
    )
    monkeypatch.setattr(signal_pending, "batch_update_signals", lambda *_args, **_kwargs: writes.append("update"))

    confirmed = signal_pending.run_step2_5(
        signal_date="2026-05-19",
        triggers={"sos": [("000001", 1.0)]},
        df_map={"000001": object()},
        dry_run=True,
    )

    assert confirmed == [{"code": "000001"}]
    assert writes == []


def test_shadow_observation_inputs_build_added_and_removed_sources():
    import scripts.daily_job as daily_job

    triggers, source_map, score_map = daily_job._shadow_observation_inputs(
        {
            "shadow_added": ["000001"],
            "shadow_removed": ["000002"],
            "shadow_score_map": {"000001": 3.5, "000002": 1.2},
        }
    )

    assert triggers == {"shadow_added": [("000001", 3.5)], "shadow_removed": [("000002", 1.2)]}
    assert source_map == {"000001": "shadow_added", "000002": "shadow_removed"}
    assert score_map["000001"] == 3.5


def test_persist_signal_observations_reports_write_failure(monkeypatch):
    import integrations.supabase_signal_feedback as signal_feedback
    import scripts.daily_job as daily_job

    monkeypatch.setattr(daily_job, "_latest_trade_date_str", lambda: "2026-05-25")
    monkeypatch.setattr(
        signal_feedback,
        "upsert_signal_observations",
        lambda _rows: (_ for _ in ()).throw(RuntimeError("upsert failed")),
    )

    ok = daily_job._persist_signal_observations(
        {"triggers": {"sos": [("000001", 1.0)]}},
        {"regime": "NEUTRAL"},
        [],
        None,
    )

    assert ok is False


def test_step3_input_preview_sends_summary_and_writes_artifact(monkeypatch, tmp_path):
    import scripts.step3_batch_report as step3

    sent: dict[str, str] = {}
    artifact_path = tmp_path / "step3_llm_input_preview.md"
    monkeypatch.setenv("STEP3_INPUT_PREVIEW_PATH", str(artifact_path))
    monkeypatch.setenv("FEISHU_INPUT_PREVIEW_AS_FILE", "1")
    monkeypatch.setenv("GITHUB_SERVER_URL", "https://github.com")
    monkeypatch.setenv("GITHUB_REPOSITORY", "YoungCan-Wang/WyckoffTradingAgent")
    monkeypatch.setenv("GITHUB_RUN_ID", "123")
    monkeypatch.setenv("GITHUB_RUN_NUMBER", "456")

    def fake_send_feishu(_webhook_url, title, content):
        sent["title"] = title
        sent["content"] = content
        return True

    monkeypatch.setattr(step3, "send_feishu_notification", fake_send_feishu)
    monkeypatch.setattr(step3, "send_feishu_file", lambda path: path == str(artifact_path))

    ok, report = step3._send_input_preview(
        webhook_url="https://example.invalid/hook",
        model="gemini-test",
        system_prompt="SYSTEM PROMPT BODY",
        previews=[{"track": "Trend", "selected_count": 2, "user_message": "VERY LONG USER MESSAGE"}],
    )

    assert ok is True
    assert report == artifact_path.read_text(encoding="utf-8")
    assert "SYSTEM PROMPT BODY" in report
    assert "VERY LONG USER MESSAGE" in report
    assert "SYSTEM PROMPT BODY" not in sent["content"]
    assert "VERY LONG USER MESSAGE" not in sent["content"]
    assert "step3_llm_input_preview.md" in sent["content"]
    assert "input-preview-logs-456" in sent["content"]
    assert "https://github.com/YoungCan-Wang/WyckoffTradingAgent/actions/runs/123" in sent["content"]


def test_step3_input_preview_falls_back_to_original_when_file_send_fails(monkeypatch, tmp_path):
    import scripts.step3_batch_report as step3

    sent: dict[str, str] = {}
    monkeypatch.setenv("STEP3_INPUT_PREVIEW_PATH", str(tmp_path / "step3_llm_input_preview.md"))
    monkeypatch.setenv("FEISHU_INPUT_PREVIEW_AS_FILE", "1")
    monkeypatch.setattr(step3, "send_feishu_file", lambda _path: False)
    monkeypatch.setattr(
        step3,
        "send_feishu_notification",
        lambda _webhook_url, _title, content: sent.setdefault("content", content) is not None,
    )

    ok, _report = step3._send_input_preview(
        webhook_url="https://example.invalid/hook",
        model="gemini-test",
        system_prompt="SYSTEM PROMPT BODY",
        previews=[{"track": "Trend", "selected_count": 2, "user_message": "VERY LONG USER MESSAGE"}],
    )

    assert ok is True
    assert "SYSTEM PROMPT BODY" in sent["content"]
    assert "VERY LONG USER MESSAGE" in sent["content"]
