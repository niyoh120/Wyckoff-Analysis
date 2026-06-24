from workflows.daily_job_common import Step2StageResult
from workflows.daily_job_runtime import DailyJobConfig
from workflows.daily_job_step2 import persist_step2_outputs


def _cfg() -> DailyJobConfig:
    return DailyJobConfig(
        webhook="",
        wecom_webhook="",
        dingtalk_webhook="",
        provider="gemini",
        api_key="",
        model="",
        llm_base_url="",
        base_url_env_key="GEMINI_BASE_URL",
        step4_provider="efficiency",
        step4_api_key="",
        step4_model="",
        step4_base_url="",
        step3_skip_llm=True,
        skip_step4=True,
        preview_only=True,
        logs_path="",
    )


def test_persist_step2_outputs_skips_recommendations_in_observe_only_market(monkeypatch) -> None:
    import workflows.daily_job_step2 as step2_module

    persisted: list[str] = []
    monkeypatch.setattr(step2_module, "persist_step2_observations", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(step2_module, "run_signal_confirmation", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(step2_module, "run_springboard_scoring", lambda *_args, **_kwargs: 1)
    monkeypatch.setattr(step2_module.daily_persistence, "persist_benchmark_context", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        step2_module.daily_persistence,
        "recommendation_write_symbols",
        lambda symbols: persisted.append("filtered") or symbols,
    )
    monkeypatch.setattr(
        step2_module.daily_persistence,
        "persist_recommendations",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should not write recommendations")),
    )

    result = Step2StageResult(
        ok=True,
        symbols_info=[{"code": "000001", "name": "平安银行"}],
        benchmark_context={"regime": "BEAR_REBOUND"},
        details={"triggers": {}, "all_df_map": {}},
        summary_item={},
        blocking_failure=False,
    )

    recommend_date, payload = persist_step2_outputs(result, _cfg())

    assert recommend_date is None
    assert payload == []
    assert persisted == []
    assert result.details["step3_symbols_info"] == []
    assert result.details["trade_mode"]["mode"] == "observe_only"
