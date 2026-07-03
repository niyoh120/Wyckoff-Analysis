from __future__ import annotations

import json
import logging
import math
import os
import sys
import traceback
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from core.candidate_guards import candidate_guard_summary, policy_candidate_guard_summary
from core.candidate_policy import candidate_score_value
from core.candidate_quality import split_ai_review_candidates
from tools.funnel_public import public_funnel_metrics
from workflows.recommendation_event_eval_summary import recommendation_event_eval_result_summary

logger = logging.getLogger(__name__)


def _sanitize(obj: Any) -> Any:
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if obj is None or isinstance(obj, (str, int, bool)):
        return obj
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {str(k): _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_sanitize(x) for x in obj]
    if hasattr(obj, "item"):
        from contextlib import suppress

        with suppress(Exception):
            return _sanitize(obj.item())
    return str(obj)


def _write_result(path: str, payload: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as f:
        json.dump(_sanitize(payload), f, ensure_ascii=False, indent=2, allow_nan=False)


def _load_payload(raw: str) -> dict[str, Any]:
    text = str(raw or "").strip()
    if not text:
        return {}
    data = json.loads(text)
    return data if isinstance(data, dict) else {}


def _apply_funnel_env(payload: dict[str, Any]) -> None:
    pool_mode = str(payload.get("pool_mode", "") or "").strip().lower()
    if pool_mode in {"manual", "board"}:
        os.environ["FUNNEL_POOL_MODE"] = pool_mode
    board = str(payload.get("board", "") or "").strip().lower()
    if board:
        os.environ["FUNNEL_POOL_BOARD"] = board
    manual_symbols = str(payload.get("manual_symbols", "") or "").strip()
    if manual_symbols:
        os.environ["FUNNEL_POOL_MANUAL_SYMBOLS"] = manual_symbols
    limit_count = payload.get("limit_count")
    if limit_count not in {None, ""}:
        os.environ["FUNNEL_POOL_LIMIT_COUNT"] = str(limit_count)

    env_map = {
        "trading_days": "FUNNEL_TRADING_DAYS",
        "max_workers": "FUNNEL_MAX_WORKERS",
        "batch_size": "FUNNEL_BATCH_SIZE",
        "min_market_cap_yi": "FUNNEL_CFG_MIN_MARKET_CAP_YI",
        "min_avg_amount_wan": "FUNNEL_CFG_MIN_AVG_AMOUNT_WAN",
        "ma_short": "FUNNEL_CFG_MA_SHORT",
        "ma_long": "FUNNEL_CFG_MA_LONG",
        "ma_hold": "FUNNEL_CFG_MA_HOLD",
        "top_n_sectors": "FUNNEL_CFG_TOP_N_SECTORS",
        "spring_support_window": "FUNNEL_CFG_SPRING_SUPPORT_WINDOW",
        "lps_vol_dry_ratio": "FUNNEL_CFG_LPS_VOL_DRY_RATIO",
        "evr_vol_ratio": "FUNNEL_CFG_EVR_VOL_RATIO",
    }
    for key, env_name in env_map.items():
        value = payload.get(key)
        if value not in {None, ""}:
            os.environ[env_name] = str(value)


def _run_funnel_screen(request_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    _apply_funnel_env(payload)
    from workflows.wyckoff_funnel import run as run_funnel

    ok, symbols_for_report, benchmark_context, details = run_funnel(
        "",
        notify=False,
        return_details=True,
    )
    metrics = public_funnel_metrics(details.get("metrics", {}) or {})
    triggers = details.get("triggers", {}) or {}
    name_map = details.get("name_map", {}) or {}
    sector_map = details.get("sector_map", {}) or {}

    trigger_groups: dict[str, list[dict[str, Any]]] = {}
    unique_hit_codes: set[str] = set()
    for trigger_name, rows in triggers.items():
        group_rows: list[dict[str, Any]] = []
        for code, score in rows:
            code_s = str(code).strip()
            if code_s:
                unique_hit_codes.add(code_s)
            group_rows.append(
                {
                    "code": code_s,
                    "name": str(name_map.get(code_s, code_s)),
                    "industry": str(sector_map.get(code_s, "") or "未知行业"),
                    "score": candidate_score_value(score),
                }
            )
        trigger_groups[str(trigger_name)] = group_rows

    ai_review_split = split_ai_review_candidates(list(symbols_for_report or []), selected_required=False)
    filtered_symbols_for_report = list(ai_review_split.get("report_candidates") or [])
    handoff = _funnel_screen_handoff(details, metrics, trigger_groups, filtered_symbols_for_report)
    result = {
        "request_id": request_id,
        "job_kind": "funnel_screen",
        "ok": bool(ok),
        "benchmark_context": benchmark_context,
        "metrics": metrics,
        "summary": {
            "total_symbols": int(metrics.get("total_symbols", 0) or 0),
            "layer1": int(metrics.get("layer1", 0) or 0),
            "layer2": int(metrics.get("layer2", 0) or 0),
            "layer3": int(metrics.get("layer3", 0) or 0),
            "l4_unique_hits": int(len(unique_hit_codes)),
            "selected_for_ai": int(len(details.get("selected_for_ai", []) or [])),
        },
        "trigger_groups": trigger_groups,
        "symbols_for_report": filtered_symbols_for_report,
        "report_candidates": filtered_symbols_for_report,
        "watch_candidates": list(ai_review_split.get("watch_candidates") or []),
        "selected_for_ai": details.get("selected_for_ai", []) or [],
        "trend_selected": details.get("trend_selected", []) or [],
        "accum_selected": details.get("accum_selected", []) or [],
        "top_sectors": metrics.get("top_sectors", []) or [],
        "content_preview": str(details.get("content", "") or "")[:4000],
        **handoff,
    }
    if quality_gate := ai_review_split.get("quality_gate"):
        result["quality_gate"] = quality_gate
    return result


def _funnel_screen_handoff(
    details: dict[str, Any],
    metrics: dict[str, Any],
    trigger_groups: dict[str, list[dict[str, Any]]],
    symbols_for_report: list[Any],
) -> dict[str, Any]:
    top_candidates = _funnel_top_candidates(trigger_groups, symbols_for_report)
    trade_mode = _trade_mode_summary(details)
    data_quality = _funnel_data_quality(metrics)
    selection_brief = _selection_brief(trade_mode, top_candidates, data_quality)
    action_plan = _action_plan(trade_mode, top_candidates, data_quality)
    next_tool = _next_tool(action_plan)
    payload = {
        "top_candidates": top_candidates,
        "data_quality": data_quality,
        "trade_mode": trade_mode,
        "decision_brief": _decision_brief(trade_mode, action_plan),
        "selection_brief": selection_brief,
        "action_plan": action_plan,
        "next_tool": next_tool,
        "next_action": _next_action(selection_brief, action_plan, next_tool),
    }
    if guard := candidate_guard_summary(_guard_rows(selection_brief, action_plan)):
        payload["candidate_guard_summary"] = guard
    return payload


def _funnel_top_candidates(
    trigger_groups: dict[str, list[dict[str, Any]]], symbols_for_report: list[Any]
) -> list[dict]:
    report_rows = _report_rows(symbols_for_report)
    rows: dict[str, dict[str, Any]] = {}
    for trigger_name, candidates in trigger_groups.items():
        for item in candidates:
            code = str(item.get("code") or "").strip()
            if not code:
                continue
            row = rows.setdefault(code, _candidate_row(code, item.get("name"), report_rows.get(code)))
            row["score"] = max(candidate_score_value(row.get("score")), candidate_score_value(item.get("score")))
            if trigger_name not in row["triggers"]:
                row["triggers"].append(trigger_name)
    for code, report_row in report_rows.items():
        rows.setdefault(code, _candidate_row(code, report_row.get("name"), report_row))
    return sorted(rows.values(), key=lambda row: (-candidate_score_value(row.get("score")), row.get("code", "")))[:20]


def _candidate_row(code: str, name: Any, report_row: dict[str, Any] | None) -> dict[str, Any]:
    row = dict(report_row or {})
    row.update({"code": code, "name": str(row.get("name") or name or code), "triggers": [], "score": 0.0})
    if report_row:
        row["selected_for_report"] = True
    return row


def _report_rows(symbols_for_report: list[Any]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for item in symbols_for_report:
        code = str((item.get("code") if isinstance(item, dict) else item) or "").strip()
        if code:
            rows[code] = dict(item) if isinstance(item, dict) else {"code": code}
    return rows


def _trade_mode_summary(details: dict[str, Any]) -> dict[str, Any]:
    mode = details.get("trade_mode") if isinstance(details.get("trade_mode"), dict) else {}
    fields = ("mode", "action", "reason", "allow_ai_review", "allow_recommendation_write")
    return {field: mode[field] for field in fields if field in mode}


def _funnel_data_quality(metrics: dict[str, Any]) -> dict[str, Any]:
    total = int(metrics.get("total_symbols", 0) or 0)
    fetch_ok = int(metrics.get("fetch_ok", 0) or 0)
    coverage_pct = round((fetch_ok / total) * 100, 1) if total else 0.0
    status = "ok" if total and coverage_pct >= 98.0 else "empty" if not total else "partial"
    return {"status": status, "coverage_pct": coverage_pct, "fetch_ok": fetch_ok}


def _selection_brief(trade_mode: dict, top_candidates: list[dict], data_quality: dict) -> dict[str, Any]:
    report = [row for row in top_candidates if row.get("selected_for_report")]
    candidates = report or top_candidates[:3]
    status = _selection_status(report, candidates, trade_mode, data_quality)
    best = [_candidate_item(row, status, trade_mode) for row in candidates[:5]]
    return {
        "status": status,
        "headline": _selection_headline(status, best),
        "best_codes": [row["code"] for row in best],
        "primary_pick": best[0] if best else {},
        "best_candidates": best,
    }


def _selection_status(report: list[dict], candidates: list[dict], trade_mode: dict, data_quality: dict) -> str:
    if not candidates:
        return "empty"
    if report and data_quality.get("status") == "empty":
        return "blocked_by_data_quality"
    if report and trade_mode.get("allow_ai_review"):
        return "ready_for_ai_review"
    if report:
        return "blocked_by_market_gate"
    return "watch_only"


def _candidate_item(row: dict[str, Any], status: str, trade_mode: dict[str, Any]) -> dict[str, Any]:
    return {
        "code": row.get("code"),
        "name": row.get("name"),
        "score": row.get("score"),
        "candidate_shadow_score": row.get("candidate_shadow_score"),
        "risk_adjusted_quality_score": row.get("risk_adjusted_quality_score"),
        "action_status": status,
        "new_buy_allowed": bool(trade_mode.get("allow_recommendation_write")) and status == "ready_for_ai_review",
        "next_step": _candidate_next_step(status),
    }


def _candidate_next_step(status: str) -> str:
    if status == "ready_for_ai_review":
        return "进入AI复核，先确认候选质量"
    if status == "blocked_by_data_quality":
        return "数据质量不足，先重跑或缩小扫描范围"
    if status == "blocked_by_market_gate":
        return "市场闸门未打开，先观察候选"
    return "观察池跟踪，暂不进入本轮AI复核"


def _selection_headline(status: str, best: list[dict[str, Any]]) -> str:
    if not best:
        return "本轮没有形成可复核候选"
    prefix = {
        "ready_for_ai_review": "本轮首选可进入 AI 研报复核",
        "blocked_by_data_quality": "本轮有候选，但数据质量未过关",
        "blocked_by_market_gate": "本轮有强候选，但市场闸门未打开",
        "watch_only": "本轮只有观察候选",
    }.get(status, "本轮候选摘要")
    return f"{prefix}: {best[0].get('code')} {best[0].get('name')}"


def _action_plan(trade_mode: dict, top_candidates: list[dict], data_quality: dict) -> dict[str, Any]:
    report = [row for row in top_candidates if row.get("selected_for_report")]
    codes = [str(row.get("code")) for row in report if row.get("code")]
    status = _review_status(codes, trade_mode, data_quality)
    return {
        "candidate_action": str(trade_mode.get("action") or "先复核候选质量"),
        "new_buy_allowed": bool(codes) and bool(trade_mode.get("allow_recommendation_write")) and status == "ready",
        "ai_review_allowed": bool(codes) and bool(trade_mode.get("allow_ai_review")) and status == "ready",
        "review_targets": _review_targets(codes, status, trade_mode),
        "report_candidates": [_candidate_item(row, "ready_for_ai_review", trade_mode) for row in report[:5]],
        "watch_candidates": [
            _candidate_item(row, "watch_only", trade_mode) for row in top_candidates if row not in report
        ][:5],
    }


def _review_status(codes: list[str], trade_mode: dict, data_quality: dict) -> str:
    if not codes:
        return "empty"
    if data_quality.get("status") == "empty":
        return "blocked_by_data_quality"
    return "ready" if trade_mode.get("allow_ai_review") else "blocked"


def _review_targets(codes: list[str], status: str, trade_mode: dict[str, Any]) -> dict[str, Any]:
    payload = {"codes": codes[:10], "status": status, "reason": str(trade_mode.get("reason") or "")}
    if status == "ready":
        payload.update({"tool": "generate_ai_report", "args": {"stock_codes": payload["codes"]}})
    return payload


def _next_tool(action_plan: dict) -> dict[str, Any]:
    review = action_plan.get("review_targets") if isinstance(action_plan, dict) else {}
    if isinstance(review, dict) and review.get("tool"):
        return {"tool": review["tool"], "args": review.get("args", {}), "reason": "候选已可进入 AI 研报复核"}
    return {}


def _next_action(selection_brief: dict, action_plan: dict, next_tool: dict) -> str:
    if next_tool:
        return str(next_tool.get("reason") or "调用下一步工具复核候选")
    return str(selection_brief.get("headline") or action_plan.get("candidate_action") or "继续复核筛股结果")


def _decision_brief(trade_mode: dict, action_plan: dict) -> dict[str, Any]:
    return {"market_gate": str(trade_mode.get("reason") or ""), "next_action": action_plan.get("candidate_action")}


def _guard_rows(selection_brief: dict, action_plan: dict) -> list[dict]:
    rows = list(selection_brief.get("best_candidates") or [])
    rows.extend(action_plan.get("report_candidates") or [])
    rows.extend(action_plan.get("watch_candidates") or [])
    return [row for row in rows if isinstance(row, dict)]


def _resolve_model_credentials(payload: dict[str, Any]) -> tuple[str, str, str, str]:
    from integrations._llm_types import DEFAULT_GEMINI_MODEL, OPENAI_COMPATIBLE_BASE_URLS, SUPPORTED_PROVIDERS

    user_id = str(payload.get("user_id", "") or "").strip()
    provider = str(payload.get("provider", "") or "gemini").strip().lower()
    if provider not in SUPPORTED_PROVIDERS:
        provider = "gemini"
    api_key = str(payload.get("api_key", "") or "").strip()
    model = str(payload.get("model", "") or "").strip()
    base_url = str(payload.get("base_url", "") or "").strip()

    key_field = f"{provider}_api_key"
    model_field = f"{provider}_model"
    base_url_field = f"{provider}_base_url"
    env_api_key = f"{provider.upper()}_API_KEY"
    env_model = f"{provider.upper()}_MODEL"
    env_base_url = f"{provider.upper()}_BASE_URL"
    if user_id:
        from integrations.supabase_portfolio import load_user_settings_admin

        settings = load_user_settings_admin(user_id) or {}
        custom_providers = settings.get("custom_providers") or {}
        if isinstance(custom_providers, str):
            try:
                custom_providers = json.loads(custom_providers)
            except Exception:
                custom_providers = {}
        if not isinstance(custom_providers, dict):
            custom_providers = {}

        api_key = str(settings.get(key_field, "") or "").strip()
        if not model:
            model = str(settings.get(model_field, "") or "").strip()
        if not base_url:
            base_url = str(settings.get(base_url_field, "") or "").strip()

        provider_entry = custom_providers.get(provider) or {}
        if isinstance(provider_entry, dict):
            if not api_key:
                api_key = str(provider_entry.get("apikey") or provider_entry.get("api_key") or "").strip()
            if not model:
                model = str(provider_entry.get("model") or "").strip()
            if not base_url:
                base_url = str(provider_entry.get("baseurl") or provider_entry.get("base_url") or "").strip()
    if not api_key:
        api_key = str(os.getenv(env_api_key, "") or "").strip()
    if not api_key and provider == "gemini":
        api_key = str(os.getenv("GEMINI_API_KEY", "") or "").strip()
    if not model:
        model = str(os.getenv(env_model, "") or "").strip()
    if not model and provider == "gemini":
        model = str(os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL) or "").strip()
    if not base_url:
        base_url = str(os.getenv(env_base_url, "") or "").strip()
    if not base_url:
        base_url = str(OPENAI_COMPATIBLE_BASE_URLS.get(provider, "") or "").strip()
    if not api_key:
        logger.warning("[resolve_credentials] 未找到可用的 %s API Key，将以 noLLM 模式运行", provider)
    if not model and api_key:
        raise ValueError(f"未找到可用的 {provider} 模型名（payload / 用户配置 / 环境变量均为空）")
    return provider, api_key, model, base_url


def _run_batch_ai_report(request_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    symbols_info = payload.get("symbols_info")
    if not isinstance(symbols_info, list) or not symbols_info:
        raise ValueError("symbols_info 为空")

    preview_only = bool(payload.get("preview_only"))
    if preview_only:
        os.environ["STEP3_SKIP_LLM"] = "1"

    provider, api_key, model, base_url = _resolve_model_credentials(payload)
    webhook_url = str(payload.get("webhook_url", "") or "").strip()
    benchmark_context = payload.get("benchmark_context", {}) or {}

    from workflows.step3_batch_report import run as run_step3

    ok, reason, report_text = run_step3(
        symbols_info,
        webhook_url=webhook_url,
        api_key=api_key,
        model=model,
        benchmark_context=benchmark_context,
        notify=bool(webhook_url),
        provider=provider,
        llm_base_url=base_url,
    )
    return {
        "request_id": request_id,
        "job_kind": "batch_ai_report",
        "ok": bool(ok),
        "reason": str(reason or ""),
        "provider": provider,
        "model": model,
        "base_url": base_url,
        "webhook_url": webhook_url,
        "preview_only": preview_only,
        "symbol_count": len(symbols_info),
        "symbols_info": symbols_info,
        "benchmark_context": benchmark_context,
        "report_text": str(report_text or ""),
    }


def _run_recommendation_event_eval(request_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    from workflows.recommendation_event_eval import RecommendationEventEvalRequest, build_recommendation_event_eval

    request = RecommendationEventEvalRequest(
        market=_payload_str(payload, "market", "cn"),
        horizon_days=_payload_int(payload, "horizon_days", 5),
        target_pct=_payload_float(payload, "target_pct", 10.0),
        max_dates=_payload_int(payload, "max_dates", 30),
        kline_count=_payload_int(payload, "kline_count", 160),
        output_dir=_payload_str(payload, "output_dir", "artifacts/recommendation_event_eval"),
        top_k=_payload_top_k(payload.get("top_k")),
    )
    result = build_recommendation_event_eval(request)
    output = {
        "request_id": request_id,
        "job_kind": "recommendation_event_eval",
        "ok": True,
        "result_summary": recommendation_event_eval_result_summary(result),
        "metadata": result["metadata"],
        "summary": result["summary"],
        "policy_selection": result["policy_selection"],
        "daily": result["daily"],
    }
    if guard_summary := policy_candidate_guard_summary(result.get("policy_selection"), result):
        output["candidate_guard_summary"] = guard_summary
    return output


def _payload_str(payload: dict[str, Any], key: str, default: str) -> str:
    value = str(payload.get(key, "") or "").strip()
    return value or default


def _payload_int(payload: dict[str, Any], key: str, default: int) -> int:
    try:
        return int(payload.get(key, default))
    except (TypeError, ValueError):
        return default


def _payload_float(payload: dict[str, Any], key: str, default: float) -> float:
    try:
        return float(payload.get(key, default))
    except (TypeError, ValueError):
        return default


def _payload_top_k(raw: Any) -> tuple[int, ...]:
    if isinstance(raw, list):
        values = [int(item) for item in raw if str(item).strip()]
    else:
        values = [int(item.strip()) for item in str(raw or "1,3,5").split(",") if item.strip()]
    return tuple(values or [1, 3, 5])


def run_web_background_job(args) -> int:
    payload = _load_payload(args.payload_json)
    requested_by_user_id = str(payload.get("user_id", "") or "").strip()

    # 注入用户配置的环境变量（Tushare Token 等）
    if requested_by_user_id:
        try:
            from integrations.supabase_portfolio import load_user_settings_admin

            user_settings = load_user_settings_admin(requested_by_user_id)
            if user_settings:
                ts_token = str(user_settings.get("tushare_token") or "").strip()
                if ts_token:
                    os.environ["TUSHARE_TOKEN"] = ts_token
                    # print(f"[web_background_job] 已注入用户 {requested_by_user_id[:8]} 的 Tushare Token")
        except Exception as e:
            print(f"[web_background_job] 注入用户配置失败: {e}")

    base_result: dict[str, Any] = {
        "request_id": args.request_id,
        "job_kind": args.job_kind,
        "requested_by_user_id": requested_by_user_id,
        "created_at": datetime.now(UTC).isoformat(),
        "status": "success",
    }

    try:
        if args.job_kind == "funnel_screen":
            result = _run_funnel_screen(args.request_id, payload)
        elif args.job_kind == "batch_ai_report":
            result = _run_batch_ai_report(args.request_id, payload)
        elif args.job_kind == "recommendation_event_eval":
            result = _run_recommendation_event_eval(args.request_id, payload)
        else:
            raise ValueError(f"不支持的 job_kind: {args.job_kind}")
        base_result.update(result)
    except Exception as e:
        base_result.update(
            {
                "status": "error",
                "ok": False,
                "error": str(e),
                "traceback": traceback.format_exc(),
            }
        )
        _write_result(args.output, base_result)
        print(base_result["traceback"], file=sys.stderr)
        return 1

    _write_result(args.output, base_result)
    print(
        f"[web_background_job] finished kind={args.job_kind} request_id={args.request_id} "
        f"user_id={requested_by_user_id or '-'}"
    )
    if not base_result.get("ok", True):
        return 1
    return 0
