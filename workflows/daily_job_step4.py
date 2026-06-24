"""Step4 OMS stage for the daily job."""

from __future__ import annotations

from workflows.daily_job_common import log_line, stage_summary
from workflows.daily_job_runtime import DailyJobConfig
from workflows.step4_holdings_diagnosis import run_step4_holdings_diagnosis
from workflows.step4_pipeline import load_step4_target, run_step4_pipeline


def run_step4_stage(
    *,
    cfg: DailyJobConfig,
    symbols_info: list[dict],
    step3_springboard_codes: list[str],
    step3_report_text: str,
    benchmark_context: dict,
) -> dict:
    if cfg.skip_step4:
        log_line("Step4 私人再平衡: 跳过（DAILY_JOB_SKIP_STEP4=1）", cfg.logs_path)
        return stage_summary("私人再平衡", "skipped (DAILY_JOB_SKIP_STEP4=1)")

    step4_target, reason = load_step4_target()
    if not step4_target:
        log_line(f"Step4 私人再平衡: 跳过（{reason}）", cfg.logs_path)
        return stage_summary("私人再平衡", f"skipped ({reason})")

    holdings_intraday_report = run_step4_holdings_diagnosis(
        str(step4_target.get("portfolio_id", "") or ""),
        cfg.logs_path,
        log_line,
    )
    return run_step4_pipeline(
        step4_target=step4_target,
        symbols_info=symbols_info,
        step3_springboard_codes=step3_springboard_codes,
        step3_report_text=step3_report_text,
        benchmark_context=benchmark_context,
        api_key=cfg.step4_api_key,
        model=cfg.step4_model,
        provider=cfg.step4_provider,
        llm_base_url=cfg.step4_base_url,
        logs_path=cfg.logs_path,
        holdings_intraday_report=holdings_intraday_report,
    )
