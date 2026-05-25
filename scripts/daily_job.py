"""
定时任务主入口：Wyckoff Funnel（Step2） → 批量研报（Step3） → 私人再平衡（Step4）

配置来源：仅读取环境变量（GitHub Secrets），与用户侧配置（Supabase）完全独立。
环境变量：FEISHU_WEBHOOK_URL, WECOM_WEBHOOK_URL(可选), DINGTALK_WEBHOOK_URL(可选),
DEFAULT_LLM_PROVIDER(可选，默认 gemini), GEMINI_API_KEY, GEMINI_MODEL,
OPENAI_API_KEY, OPENAI_MODEL(可选), 以及其它厂商 *_API_KEY/*_MODEL/*_BASE_URL,
SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY(可选), SUPABASE_USER_ID,
TG_BOT_TOKEN, TG_CHAT_ID, MY_PORTFOLIO_STATE(可选兜底),
STEP3_SKIP_LLM(可选), DAILY_JOB_SKIP_STEP4(可选), DAILY_JOB_PREVIEW_ONLY(可选), LOGS_DIR(可选)
"""

from __future__ import annotations

import argparse
import os
import sys
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# Ensure project root is on sys.path for direct script invocation
if __name__ == "__main__" or not __package__:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from integrations._llm_types import DEFAULT_GEMINI_MODEL, OPENAI_COMPATIBLE_BASE_URLS
from integrations.fetch_a_share_csv import _resolve_trading_window
from integrations.supabase_market_signal import upsert_market_signal_daily
from integrations.supabase_recommendation import (
    mark_ai_recommendations,
    upsert_recommendations,
)
from utils.trading_clock import next_trading_day, resolve_end_calendar_day

TZ = ZoneInfo("Asia/Shanghai")
STEP3_REASON_MAP = {
    "data_all_failed": "OHLCV 全部拉取失败",
    "llm_failed": "大模型调用失败",
    "feishu_failed": "飞书推送失败",
    "skipped_no_symbols": "无输入股票，已跳过",
    "no_data_but_no_error": "无可用数据",
    "ok_preview": "预演模式：未调用模型，仅展示输入",
}
STEP4_REASON_MAP = {
    "missing_api_key": "GEMINI_API_KEY 缺失",
    "skipped_invalid_portfolio": "用户持仓缺失或格式错误，已跳过",
    "skipped_telegram_unconfigured": "Telegram 未配置，已跳过",
    "skipped_idempotency": "今日已运行，已跳过",
    "skipped_no_decisions": "模型未给出有效决策，已跳过",
    "llm_failed": "Step4 模型调用失败",
    "telegram_failed": "Telegram 推送失败",
    "ok": "ok",
}


def _env_flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _now() -> str:
    return datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")


def _log(msg: str, logs_path: str | None = None) -> None:
    line = f"[{_now()}] {msg}"
    print(line, flush=True)
    if logs_path:
        os.makedirs(os.path.dirname(logs_path) or ".", exist_ok=True)
        with open(logs_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def _notify_skip(msg: str, feishu: str = "", wecom: str = "", dingtalk: str = "") -> None:
    """非交易日跳过时，通过已配置的 IM 渠道发送通知。"""
    from contextlib import suppress

    if feishu:
        with suppress(Exception):
            from utils.feishu import send_feishu_notification

            send_feishu_notification(feishu, "定时任务跳过", msg)
    if wecom:
        with suppress(Exception):
            from utils.notify import send_wecom_notification

            send_wecom_notification(wecom, "定时任务跳过", msg)
    if dingtalk:
        with suppress(Exception):
            from utils.notify import send_dingtalk_notification

            send_dingtalk_notification(dingtalk, "定时任务跳过", msg)


class _TeeStream:
    """将 print 输出同时写到终端和日志文件。"""

    def __init__(self, console_stream, file_stream):
        self.console_stream = console_stream
        self.file_stream = file_stream

    def write(self, data: str) -> int:
        self.console_stream.write(data)
        self.file_stream.write(data)
        return len(data)

    def flush(self) -> None:
        self.console_stream.flush()
        self.file_stream.flush()


def _run_with_stdout_tee(logs_path: str | None, fn, *args, **kwargs):
    """运行子步骤时，将其 stdout/stderr 透传到 daily_job 日志文件。"""
    if not logs_path:
        return fn(*args, **kwargs)
    os.makedirs(os.path.dirname(logs_path) or ".", exist_ok=True)
    with open(logs_path, "a", encoding="utf-8") as log_file:
        tee = _TeeStream(sys.stdout, log_file)
        with redirect_stdout(tee), redirect_stderr(tee):
            return fn(*args, **kwargs)


def _latest_trade_date_str() -> str:
    window = _resolve_trading_window(
        end_calendar_day=resolve_end_calendar_day(),
        trading_days=30,
    )
    return window.end_trade_date.isoformat()


def _persist_benchmark_context(
    benchmark_context: dict,
    logs_path: str | None = None,
    *,
    dry_run: bool = False,
) -> None:
    if not benchmark_context:
        return
    if dry_run:
        _log("预演模式: 跳过市场信号写库(benchmark)", logs_path)
        return
    trade_date = _latest_trade_date_str()
    payload = {
        "benchmark_regime": str(benchmark_context.get("regime", "") or "").strip().upper() or None,
        "main_index_code": str(benchmark_context.get("main_code", "000001") or "000001").strip(),
        "main_index_close": benchmark_context.get("close"),
        "main_index_ma50": benchmark_context.get("ma50"),
        "main_index_ma200": benchmark_context.get("ma200"),
        "main_index_recent3_cum_pct": benchmark_context.get("recent3_cum_pct"),
        "main_index_today_pct": benchmark_context.get("main_today_pct"),
        "smallcap_index_code": str(benchmark_context.get("smallcap_code", "") or "").strip() or None,
        "smallcap_close": benchmark_context.get("smallcap_close"),
        "smallcap_recent3_cum_pct": benchmark_context.get("smallcap_recent3_cum_pct"),
        "source_jobs": {
            "daily_job": {
                "updated_at": datetime.now(TZ).isoformat(),
                "writer": "step2_benchmark_context",
            }
        },
    }
    ok = upsert_market_signal_daily(trade_date, payload)
    _log(
        f"市场信号写库(benchmark): ok={ok}, trade_date={trade_date}, regime={payload.get('benchmark_regime')}",
        logs_path,
    )


def _persist_recommendations(
    symbols_info: list[dict],
    logs_path: str | None,
    *,
    dry_run: bool = False,
) -> int | None:
    if dry_run:
        _log(f"预演模式: 跳过推荐记录入库 count={len(symbols_info)}", logs_path)
        return None
    try:
        recommend_trade_date_int = int(_latest_trade_date_str().replace("-", ""))
        rec_ok = upsert_recommendations(recommend_trade_date_int, symbols_info)
        _log(
            f"推荐记录入库: ok={rec_ok}, count={len(symbols_info)}, date={recommend_trade_date_int}",
            logs_path,
        )
        return recommend_trade_date_int
    except Exception as e:
        _log(f"推荐记录入库失败: {e}", logs_path)
        return None


def _mark_step3_recommendations(
    recommend_trade_date_int: int | None,
    step3_springboard_codes: list[str],
    logs_path: str | None,
    *,
    dry_run: bool = False,
) -> None:
    if dry_run:
        _log("预演模式: 跳过推荐记录AI标记", logs_path)
        return
    if recommend_trade_date_int is None:
        return
    try:
        ai_mark_ok = mark_ai_recommendations(
            recommend_date=recommend_trade_date_int,
            ai_codes=step3_springboard_codes,
        )
        _log(
            "推荐记录AI标记: "
            f"ok={ai_mark_ok}, date={recommend_trade_date_int}, ai_count={len(step3_springboard_codes)}",
            logs_path,
        )
    except Exception as e:
        _log(f"推荐记录AI标记失败: {e}", logs_path)


def _persist_signal_observations(
    step2_details: dict,
    benchmark_context: dict,
    ai_codes: list[str],
    logs_path: str | None,
    *,
    dry_run: bool = False,
) -> None:
    if not step2_details:
        return
    if dry_run:
        _log("预演模式: 跳过信号观察样本入库", logs_path)
        return
    try:
        from core.signal_feedback import build_signal_observations
        from integrations.supabase_signal_feedback import upsert_signal_observations

        metrics = step2_details.get("metrics", {}) or {}
        bypass_codes = {str(c).strip() for c in step2_details.get("l2_bypass_selected", []) if str(c).strip()}
        source_map = {code: "l2_bypass" for code in bypass_codes}
        rows = build_signal_observations(
            _latest_trade_date_str(),
            step2_details.get("review_triggers") or step2_details.get("triggers") or {},
            regime=str((benchmark_context or {}).get("regime") or "NEUTRAL"),
            selected_for_ai=step2_details.get("selected_for_ai", []) or [],
            ai_recommended=ai_codes,
            name_map=step2_details.get("name_map", {}) or {},
            sector_map=step2_details.get("sector_map", {}) or {},
            score_map=step2_details.get("priority_score_map", {}) or {},
            stage_map=metrics.get("accum_stage_map", {}) or {},
            channel_map=metrics.get("layer2_channel_map", {}) or {},
            latest_close_map=metrics.get("latest_close_map", {}) or {},
            source_map=source_map,
        )
        written = upsert_signal_observations(rows)
        _log(f"信号观察样本入库: rows={len(rows)}, written={written}", logs_path)
    except Exception as e:
        _log(f"信号观察样本入库失败: {e}", logs_path)


def _load_step4_target() -> tuple[dict | None, str]:
    target_user_id = os.getenv("SUPABASE_USER_ID", "").strip()
    if not target_user_id:
        return None, "SUPABASE_USER_ID 未配置"

    portfolio_id = f"USER_LIVE:{target_user_id}"
    try:
        from integrations.supabase_portfolio import load_portfolio_state
    except Exception as e:
        return None, f"supabase portfolio 读取器不可用: {e}"

    # 强制按唯一 user_id 读取目标账户
    p = load_portfolio_state(portfolio_id)
    has_env_fallback = bool(os.getenv("MY_PORTFOLIO_STATE", "").strip())
    if not isinstance(p, dict) and not has_env_fallback:
        return None, f"未匹配到 user_id={target_user_id} 的持仓（{portfolio_id}）"

    return {
        "user_id": target_user_id,
        "portfolio_id": portfolio_id,
    }, ("ok_supabase" if isinstance(p, dict) else "ok_env_fallback")


def _run_signal_confirmation(
    symbols_info: list[dict],
    step2_details: dict,
    benchmark_context: dict | None,
    logs_path: str | None,
    *,
    dry_run: bool = False,
) -> None:
    """Step2.5: pending 信号确认，confirmed 追加到 symbols_info。"""
    try:
        from integrations.supabase_signal_pending import run_step2_5

        triggers_raw = step2_details.get("triggers", {})
        all_df_map = step2_details.get("all_df_map", {})
        if triggers_raw and all_df_map:
            confirmed_extra = run_step2_5(
                signal_date=_latest_trade_date_str(),
                triggers=triggers_raw,
                df_map=all_df_map,
                regime=(benchmark_context.get("regime") or "NEUTRAL").strip().upper()
                if benchmark_context
                else "NEUTRAL",
                name_map=step2_details.get("name_map", {}),
                sector_map=step2_details.get("sector_map", {}),
                dry_run=dry_run,
            )
            suffix = "（preview dry-run，不写库）" if dry_run else ""
            _log(f"Step2.5 信号确认{suffix}: confirmed={len(confirmed_extra)}", logs_path)
            existing_codes = {str(s.get("code", "")).strip() for s in symbols_info}
            for cs in confirmed_extra:
                if str(cs.get("code", "")).strip() not in existing_codes:
                    symbols_info.append(cs)
    except Exception as e:
        _log(f"Step2.5 信号确认失败（已降级）: {e}", logs_path)


def _run_springboard_scoring(
    symbols_info: list[dict],
    step2_details: dict,
) -> int:
    """从 triggers 反查 code→signal_type，调用量化评分器。"""
    from core.signal_confirmation import score_springboard_abc

    all_df_map = step2_details.get("all_df_map", {})
    triggers = step2_details.get("triggers", {})
    code_to_sig: dict[str, str] = {}
    for sig_type, hits in triggers.items():
        for code, _ in hits:
            code_to_sig.setdefault(str(code).strip(), sig_type)

    scored = 0
    for item in symbols_info:
        code = str(item.get("code", "")).strip()
        sig_type = str(item.get("signal_type", "")).strip().lower() or code_to_sig.get(code, "")
        df = all_df_map.get(code)
        if df is None or df.empty or not sig_type:
            item["springboard_grade"] = "none"
            continue
        result = score_springboard_abc(df, sig_type)
        item["springboard_a"] = result["a"]
        item["springboard_b"] = result["b"]
        item["springboard_c"] = result["c"]
        item["springboard_grade"] = result["grade"]
        scored += 1
    return scored


def _run_step4_holdings_diagnosis(portfolio_id: str, logs_path: str | None) -> str:
    tickflow_api_key = os.getenv("TICKFLOW_API_KEY", "").strip()
    if not tickflow_api_key:
        return ""
    from integrations.tickflow_client import TickFlowClient
    from scripts.tail_buy_intraday_job import (
        _analyze_holdings_actions,
        _build_holdings_markdown,
    )

    try:
        tf_client = TickFlowClient(api_key=tickflow_api_key)
        h_list, h_limit, h_meta = _analyze_holdings_actions(
            tickflow_client=tf_client,
            portfolio_id=portfolio_id,
            signal_map={},
            style="conservative",
            intraday_batch_size=200,
            hard_stop_pct=6.0,
            deadline_at=datetime.now(TZ) + timedelta(minutes=5),
            logs_path=logs_path,
        )
        text = _build_holdings_markdown(
            holdings=h_list,
            portfolio_meta=h_meta,
            tickflow_limit_hit=h_limit,
        )
        _log(f"持仓分时诊断: {len(h_list)} positions", logs_path)
        return text
    except Exception as e:
        _log(f"持仓分时诊断失败（降级继续）: {e}", logs_path)
        return ""


def _run_step4_pipeline(
    step4_target: dict,
    symbols_info: list,
    step3_springboard_codes: list[str],
    step3_report_text: str,
    benchmark_context: dict | None,
    api_key: str,
    model: str,
    logs_path: str | None,
) -> dict:
    from core.strategy import run_step4

    t0 = datetime.now(TZ)
    tg_bot_token = os.getenv("TG_BOT_TOKEN", "").strip()
    tg_chat_id = os.getenv("TG_CHAT_ID", "").strip()
    if not tg_bot_token or not tg_chat_id:
        _log("Step4 私人再平衡: 跳过（TG_BOT_TOKEN/TG_CHAT_ID 未配置）", logs_path)
        return {
            "step": "私人再平衡",
            "ok": True,
            "err": None,
            "elapsed_s": 0,
            "output": "skipped (TG_BOT_TOKEN/TG_CHAT_ID 未配置)",
        }

    user_id = str(step4_target.get("user_id", "") or "").strip()
    portfolio_id = str(step4_target.get("portfolio_id", "") or "").strip()
    step4_candidate_meta: list[dict] = []
    if step3_springboard_codes:
        allowed_set = set(step3_springboard_codes)
        for item in symbols_info:
            if not isinstance(item, dict):
                continue
            code = str(item.get("code", "")).strip()
            if code in allowed_set:
                step4_candidate_meta.append(item)
    _log(f"Step4 私人再平衡: 候选收口为 Step3 起跳板 {len(step4_candidate_meta)} 只", logs_path)

    holdings_diag_text = _run_step4_holdings_diagnosis(portfolio_id, logs_path)

    step4_ok = True
    step4_reason = "ok"
    step4_err = None
    try:
        step4_ok, step4_reason = run_step4(
            external_report=step3_report_text,
            benchmark_context=benchmark_context,
            api_key=api_key,
            model=model,
            candidate_meta=step4_candidate_meta,
            portfolio_id=portfolio_id,
            tg_bot_token=tg_bot_token,
            tg_chat_id=tg_chat_id,
            holdings_intraday_report=holdings_diag_text,
        )
        step4_err = None if step4_ok else STEP4_REASON_MAP.get(step4_reason, step4_reason)
    except Exception as e:
        step4_ok = False
        step4_reason = "unexpected_exception"
        step4_err = str(e)
    elapsed4 = (datetime.now(TZ) - t0).total_seconds()
    _log(
        f"Step4 私人再平衡: user={user_id}, portfolio={portfolio_id}, "
        f"ok={step4_ok}, reason={step4_reason}, elapsed={elapsed4:.1f}s, err={step4_err}",
        logs_path,
    )
    return {
        "step": "私人再平衡",
        "ok": step4_ok and step4_err is None,
        "err": step4_err,
        "elapsed_s": round(elapsed4, 1),
        "output": f"user={user_id}, portfolio={portfolio_id}, reason={step4_reason}",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="每日定时任务：Wyckoff Funnel → 批量研报")
    parser.add_argument("--dry-run", action="store_true", help="仅校验配置，不执行任务")
    parser.add_argument("--logs", default=None, help="日志文件路径，默认 logs/daily_job_YYYYMMDD_HHMMSS.log")
    args = parser.parse_args()

    webhook = os.getenv("FEISHU_WEBHOOK_URL", "").strip()
    wecom_webhook = os.getenv("WECOM_WEBHOOK_URL", "").strip()
    dingtalk_webhook = os.getenv("DINGTALK_WEBHOOK_URL", "").strip()
    provider = os.getenv("DEFAULT_LLM_PROVIDER", "gemini").strip().lower() or "gemini"
    api_key = (os.getenv(f"{provider.upper()}_API_KEY") or os.getenv("GEMINI_API_KEY") or "").strip()
    model_env_key = f"{provider.upper()}_MODEL"
    model = (
        os.getenv(model_env_key) or os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)
    ).strip() or DEFAULT_GEMINI_MODEL
    base_url_env_key = f"{provider.upper()}_BASE_URL"
    llm_base_url = (os.getenv(base_url_env_key) or OPENAI_COMPATIBLE_BASE_URLS.get(provider, "") or "").strip()
    step3_skip_llm = _env_flag("STEP3_SKIP_LLM")
    skip_step4 = _env_flag("DAILY_JOB_SKIP_STEP4")
    preview_only = _env_flag("DAILY_JOB_PREVIEW_ONLY")
    if preview_only:
        os.environ["STEP3_SKIP_LLM"] = "1"
        os.environ["DAILY_JOB_SKIP_STEP4"] = "1"
    step3_skip_llm = step3_skip_llm or preview_only
    skip_step4 = skip_step4 or preview_only

    logs_path = args.logs or os.path.join(
        os.getenv("LOGS_DIR", "logs"),
        f"daily_job_{datetime.now(TZ).strftime('%Y%m%d_%H%M%S')}.log",
    )

    # Secret 完整性预检
    missing = []
    # 仅当需要调用模型时强制要求对应厂商 API Key
    require_api_key = (not step3_skip_llm) or (not skip_step4)
    if require_api_key and not api_key:
        missing.append(f"{provider.upper()}_API_KEY 或 GEMINI_API_KEY")
    if missing:
        _log(f"配置缺失: {', '.join(missing)}", logs_path)
        return 1
    # IM 渠道均为可选，未配置时仅跳过推送
    if not webhook and not wecom_webhook and not dingtalk_webhook:
        _log("未配置任何 IM 渠道（飞书/企微/钉钉），筛选与研报仍会执行，推送将被跳过", logs_path)

    if args.dry_run:
        _log("--dry-run: 配置校验通过，退出", logs_path)
        return 0

    # 非交易日跳过：检查下一个交易日是否在 2 天内（周日跑 → 周一应该开盘）
    today = datetime.now(TZ).date()
    nxt = next_trading_day(today)
    if nxt and (nxt - today).days > 2:
        skip_msg = f"📅 下一交易日 {nxt} 距今超过 2 天，任务跳过"
        _log(skip_msg, logs_path)
        _notify_skip(skip_msg, webhook, wecom_webhook, dingtalk_webhook)
        return 0

    if provider in OPENAI_COMPATIBLE_BASE_URLS:
        _log(f"LLM base_url: {llm_base_url or '(empty)'} (env={base_url_env_key})", logs_path)

    # 数据源口径在 integrations/data_source.py 中固定为：
    # tickflow 优先（前复权 qfq），失败按 tushare→akshare→baostock→efinance 回退。

    from core.batch_report import (
        extract_operation_pool_codes,
        run_step3,
    )
    from core.funnel_pipeline import run_funnel as run_step2

    summary: list[dict] = []
    has_blocking_failure = False
    symbols_info: list[dict] = []
    benchmark_context: dict = {}
    step3_report_text = ""
    recommend_trade_date_int: int | None = None

    _log("开始定时任务", logs_path)
    if preview_only:
        _log("预演模式: 仅生成 Step3 LLM input，跳过 Step2 通知和所有写库动作", logs_path)

    # Step2: Wyckoff Funnel
    t0 = datetime.now(TZ)
    step2_ok = False
    step2_err = None
    step2_details: dict = {}
    try:
        result = run_step2("" if preview_only else webhook, notify=not preview_only, return_details=True)
        step2_ok, symbols_info, benchmark_context, step2_details = result
        step2_err = None if step2_ok else "飞书发送失败"
    except Exception as e:
        step2_err = str(e)
    elapsed2 = (datetime.now(TZ) - t0).total_seconds()
    summary.append(
        {
            "step": "Wyckoff Funnel",
            "ok": step2_ok and step2_err is None,
            "err": step2_err,
            "elapsed_s": round(elapsed2, 1),
            "output": f"{len(symbols_info)} symbols",
        }
    )
    _log(
        f"Step2 Wyckoff Funnel: ok={step2_ok}, symbols={len(symbols_info)}, elapsed={elapsed2:.1f}s, err={step2_err}",
        logs_path,
    )
    if step2_err:
        has_blocking_failure = True
    elif benchmark_context:
        _persist_benchmark_context(benchmark_context, logs_path, dry_run=preview_only)

    # Step2.5: 信号确认（pending → confirmed/expired）— 必须在推荐写入前执行，
    # 使 confirmed 信号能沉淀进 recommendation_tracking
    if step2_ok and step2_details:
        _run_signal_confirmation(symbols_info, step2_details, benchmark_context, logs_path, dry_run=preview_only)

    # 形态复盘写库（按 recommend_date=最近交易日）
    if step2_ok and symbols_info:
        recommend_trade_date_int = _persist_recommendations(symbols_info, logs_path, dry_run=preview_only)

    # Step2.7: 起跳板 A/B/C 量化评分
    if symbols_info and step2_details:
        _scored = _run_springboard_scoring(symbols_info, step2_details)
        _log(f"Step2.7 起跳板评分: scored={_scored}/{len(symbols_info)}", logs_path)

    # Step3: 批量研报（可降级：失败不影响 Funnel 成功）
    step3_ok = True
    step3_err = None
    step3_springboard_codes: list[str] = []
    _regime_for_step3 = (benchmark_context.get("regime") or "").strip().upper() if benchmark_context else ""
    if symbols_info:
        t0 = datetime.now(TZ)
        try:
            step3_ok, step3_reason, step3_report_text = _run_with_stdout_tee(
                logs_path,
                run_step3,
                symbols_info,
                webhook,
                api_key,
                model,
                benchmark_context=benchmark_context,
                provider=provider,
                llm_base_url=llm_base_url,
                wecom_webhook=wecom_webhook,
                dingtalk_webhook=dingtalk_webhook,
            )
            step3_err = None if step3_ok else STEP3_REASON_MAP.get(step3_reason, step3_reason)
        except Exception as e:
            step3_ok = False
            step3_err = str(e)
        if step3_ok and step3_report_text:
            allowed_codes = [str(item.get("code", "")).strip() for item in symbols_info if isinstance(item, dict)]
            try:
                step3_springboard_codes = extract_operation_pool_codes(
                    report=step3_report_text,
                    allowed_codes=allowed_codes,
                )
            except Exception as e:
                step3_springboard_codes = []
                _log(f"Step3 批量研报: 起跳板解析失败，已降级为空。err={e}", logs_path)
        elapsed3 = (datetime.now(TZ) - t0).total_seconds()
        summary.append(
            {
                "step": "批量研报",
                "ok": step3_ok and step3_err is None,
                "err": step3_err,
                "elapsed_s": round(elapsed3, 1),
                "output": f"{len(symbols_info)} symbols",
            }
        )
        _log(f"Step3 批量研报: ok={step3_ok}, elapsed={elapsed3:.1f}s, err={step3_err}", logs_path)
        preview_codes = ", ".join(step3_springboard_codes[:8]) if step3_springboard_codes else "无"
        _log(
            f"Step3 批量研报: 起跳板代码={len(step3_springboard_codes)} ({preview_codes})",
            logs_path,
        )
        _mark_step3_recommendations(recommend_trade_date_int, step3_springboard_codes, logs_path, dry_run=preview_only)
    else:
        summary.append({"step": "批量研报", "ok": True, "err": None, "elapsed_s": 0, "output": "skipped (no symbols)"})
        _log("Step3 批量研报: 跳过（无筛选结果）", logs_path)

    if step2_ok and step2_details:
        _persist_signal_observations(
            step2_details, benchmark_context, step3_springboard_codes, logs_path, dry_run=preview_only
        )

    # Step4: 私人账户再平衡（按 SUPABASE_USER_ID 唯一执行）
    if skip_step4:
        summary.append(
            {
                "step": "私人再平衡",
                "ok": True,
                "err": None,
                "elapsed_s": 0,
                "output": "skipped (DAILY_JOB_SKIP_STEP4=1)",
            }
        )
        _log("Step4 私人再平衡: 跳过（DAILY_JOB_SKIP_STEP4=1）", logs_path)
        step4_target = None
    else:
        step4_target, step4_target_reason = _load_step4_target()
    if not skip_step4 and not step4_target:
        summary.append(
            {
                "step": "私人再平衡",
                "ok": True,
                "err": None,
                "elapsed_s": 0,
                "output": f"skipped ({step4_target_reason})",
            }
        )
        _log(f"Step4 私人再平衡: 跳过（{step4_target_reason}）", logs_path)
    elif not skip_step4:
        summary.append(
            _run_step4_pipeline(
                step4_target=step4_target,
                symbols_info=symbols_info,
                step3_springboard_codes=step3_springboard_codes,
                step3_report_text=step3_report_text,
                benchmark_context=benchmark_context,
                api_key=api_key,
                model=model,
                logs_path=logs_path,
            )
        )

    # 汇总
    total_elapsed = sum(s.get("elapsed_s", 0) for s in summary)
    _log("", logs_path)
    _log("=== 阶段汇总 ===", logs_path)
    for s in summary:
        status = "✅" if s["ok"] else "❌"
        _log(
            f"  {status} {s['step']}: {s.get('elapsed_s', 0)}s, {s.get('output', '')}"
            + (f" | {s['err']}" if s.get("err") else ""),
            logs_path,
        )
    _log(f"总耗时: {total_elapsed:.1f}s", logs_path)
    _log("定时任务结束", logs_path)

    # 阻断型失败：Funnel 失败
    if has_blocking_failure:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
