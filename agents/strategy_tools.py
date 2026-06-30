"""Agent-facing portfolio strategy decision tool."""

from __future__ import annotations

import logging
from typing import Any

from agents.report_tools import reviewed_symbols_from_info, run_ai_report, symbols_info_from_codes
from agents.screen_tools import screen_stocks
from agents.tool_context import ToolContext, ensure_tushare_token, get_credential, get_user_id, resolve_llm_config

logger = logging.getLogger(__name__)


def generate_strategy_decision(
    report_text: str = "",
    reviewed_symbols: Any = None,
    reviewed_codes: Any = None,
    screen_result: dict | None = None,
    tool_context: ToolContext | None = None,
) -> dict:
    """生成持仓去留决策和新标的买入策略。"""
    try:
        ensure_tushare_token(tool_context)
        provider, api_key, model, base_url = resolve_llm_config(tool_context)
        if not api_key:
            return {"error": "未配置 LLM API Key，无法生成策略决策。请通过 /model 或设置页面配置。"}

        last_report = _last_ai_report(tool_context)
        screen_payload = screen_result or _last_screen_result(tool_context)
        report_text, report_source = _strategy_report_text(report_text, last_report)
        if (
            not report_text
            and not screen_payload
            and not _has_candidate_inputs(reviewed_symbols, reviewed_codes, last_report)
        ):
            screen_payload = screen_stocks(board="all", tool_context=tool_context)
            if screen_payload.get("error"):
                return {"error": f"筛选失败: {screen_payload['error']}"}

        candidate_meta = _strategy_candidate_meta(
            screen_payload,
            reviewed_symbols,
            reviewed_codes,
            last_report,
            tool_context,
        )
        if not report_text:
            report_text = _report_for_candidates(candidate_meta, provider, api_key, model, base_url)
            report_source = "generated_from_candidates" if report_text else "empty"
        token = get_credential(tool_context, "tg_bot_token", "TG_BOT_TOKEN")
        chat_id = get_credential(tool_context, "tg_chat_id", "TG_CHAT_ID")
        if not token or not chat_id:
            result = _strategy_without_telegram(screen_payload or {}, report_text, candidate_meta, report_source)
            remember_strategy_decision(tool_context, result)
            return result
        ok, reason = _run_strategy_step4(
            tool_context,
            report_text,
            candidate_meta,
            provider,
            api_key,
            model,
            base_url,
            token,
            chat_id,
        )
        result = _strategy_payload(bool(ok), str(reason or ""), screen_payload or {}, candidate_meta, report_source)
        remember_strategy_decision(tool_context, result)
        return result
    except Exception as e:
        logger.exception("generate_strategy_decision error")
        return {"error": str(e)}


def _strategy_report_text(report_text: str, last_report: dict[str, Any]) -> tuple[str, str]:
    explicit = str(report_text or "").strip()
    if explicit:
        return explicit, "provided"
    previous = str(last_report.get("report_text") or "").strip()
    if previous:
        return previous, "last_ai_report"
    return "", "empty"


def _report_for_candidates(symbols_info: list[dict], provider: str, api_key: str, model: str, base_url: str) -> str:
    if not symbols_info:
        return ""
    _ok, _reason, report_text = run_ai_report(
        symbols_info[:10],
        provider=provider,
        api_key=api_key,
        model=model,
        base_url=base_url,
    )
    return str(report_text or "")


def _strategy_candidate_meta(
    screen_result: dict | None,
    reviewed_symbols: Any,
    reviewed_codes: Any,
    last_report: dict[str, Any],
    tool_context: ToolContext | None,
) -> list[dict]:
    rows = _screen_candidate_meta(screen_result)
    rows.extend(reviewed_symbols_from_info(_symbol_items(reviewed_symbols)))
    rows.extend(reviewed_symbols_from_info(_symbol_items(last_report.get("reviewed_symbols"))))
    codes = _code_items(reviewed_codes) or _code_items(last_report.get("reviewed_codes"))
    rows.extend(symbols_info_from_codes(codes, tool_context))
    return _dedupe_candidate_meta(rows)


def _has_candidate_inputs(reviewed_symbols: Any, reviewed_codes: Any, last_report: dict[str, Any]) -> bool:
    return bool(
        _symbol_items(reviewed_symbols)
        or _code_items(reviewed_codes)
        or _symbol_items(last_report.get("reviewed_symbols"))
        or _code_items(last_report.get("reviewed_codes"))
    )


def _symbol_items(value: Any) -> list[dict]:
    if isinstance(value, dict):
        return [value]
    if isinstance(value, (list, tuple, set)):
        return [item for item in value if isinstance(item, dict)]
    return []


def _code_items(value: Any) -> list[Any]:
    if value in (None, ""):
        return []
    return list(value) if isinstance(value, (list, tuple, set)) else [value]


def _screen_candidate_meta(screen_result: dict | None) -> list[dict]:
    if not isinstance(screen_result, dict):
        return []
    rows = _screen_candidate_rows(screen_result)
    return reviewed_symbols_from_info([row if isinstance(row, dict) else {"code": row} for row in rows])


def _screen_candidate_rows(screen_result: dict[str, Any]) -> list[Any]:
    rows = screen_result.get("symbols_for_report") or []
    if rows:
        return _enrich_candidate_rows(list(rows), _candidate_context_rows(screen_result))
    return _candidate_context_rows(screen_result)[:5]


def _candidate_context_rows(screen_result: dict[str, Any]) -> list[Any]:
    selection_brief = screen_result.get("selection_brief")
    if isinstance(selection_brief, dict) and isinstance(selection_brief.get("best_candidates"), list):
        return list(selection_brief["best_candidates"])
    return list(screen_result.get("top_candidates") or [])[:5]


def _enrich_candidate_rows(rows: list[Any], context_rows: list[Any]) -> list[dict]:
    context = {_row_code(row): dict(row) for row in context_rows if isinstance(row, dict) and _row_code(row)}
    enriched = []
    for row in rows:
        code = _row_code(row)
        if not code:
            continue
        payload = dict(context.get(code) or {})
        if isinstance(row, dict):
            payload.update({key: value for key, value in row.items() if _has_value(value)})
        payload["code"] = code
        enriched.append(payload)
    return enriched


def _row_code(row: Any) -> str:
    if isinstance(row, dict):
        return str(row.get("code") or row.get("symbol") or "").strip()
    return str(row or "").strip()


def _dedupe_candidate_meta(rows: list[dict]) -> list[dict]:
    deduped: dict[str, dict] = {}
    for row in rows:
        code = str(row.get("code") or "").strip()
        if not code:
            continue
        if code not in deduped:
            deduped[code] = dict(row)
            continue
        for key, value in row.items():
            if _has_value(value) and not _has_value(deduped[code].get(key)):
                deduped[code][key] = value
    return list(deduped.values())[:10]


def _has_value(value: Any) -> bool:
    return value is not None and value != "" and value != [] and value != {}


def _strategy_without_telegram(
    screen_result: dict,
    report_text: str,
    candidate_meta: list[dict],
    report_source: str,
) -> dict:
    payload = _strategy_payload(
        True,
        "skipped_notify_unconfigured",
        screen_result,
        candidate_meta,
        report_source,
    )
    payload.update(
        {
            "message": "已完成候选和研报交接，但未配置 Telegram，OMS 交易工单不会生成或发送。",
            "report_preview": (report_text[:2000] + "...") if len(report_text) > 2000 else report_text,
        }
    )
    return payload


def _strategy_payload(
    ok: bool,
    reason: str,
    screen_result: dict,
    candidate_meta: list[dict],
    report_source: str,
) -> dict:
    return {
        "ok": ok,
        "reason": reason,
        "status": reason or ("ok" if ok else "failed"),
        "report_source": report_source,
        "candidate_count": len(candidate_meta),
        "reviewed_codes": [row["code"] for row in candidate_meta if row.get("code")],
        "reviewed_symbols": candidate_meta,
        "screen_summary": screen_result.get("summary", {}),
        "decision_brief": screen_result.get("decision_brief", {}),
        "next_action": _strategy_next_action(ok, reason),
    }


def _strategy_next_action(ok: bool, reason: str) -> str:
    if reason == "skipped_notify_unconfigured":
        return "补充 Telegram 配置后可生成并发送 OMS 工单；当前先基于研报和候选摘要人工复核"
    if ok:
        return "攻防决策已完成，查看 Telegram 或订单记录确认工单"
    return "策略决策未完成，先处理失败原因后再重新生成"


def remember_strategy_decision(tool_context: ToolContext | None, result: dict[str, Any]) -> None:
    if tool_context is not None and not result.get("error"):
        tool_context.state["last_strategy_decision"] = result


def _last_ai_report(tool_context: ToolContext | None) -> dict[str, Any]:
    value = tool_context.state.get("last_ai_report") if tool_context else {}
    return value if isinstance(value, dict) else {}


def _last_screen_result(tool_context: ToolContext | None) -> dict[str, Any]:
    value = tool_context.state.get("last_screen_result") if tool_context else {}
    return value if isinstance(value, dict) else {}


def _run_strategy_step4(
    tool_context: ToolContext | None,
    report_text: str,
    candidate_meta: list[dict],
    provider: str,
    api_key: str,
    model: str,
    base_url: str,
    tg_bot_token: str,
    tg_chat_id: str,
) -> tuple[bool, str]:
    from integrations.supabase_portfolio import build_user_live_portfolio_id
    from workflows.step4_rebalancer import run as run_step4

    return run_step4(
        external_report=report_text,
        benchmark_context=None,
        api_key=api_key,
        model=model,
        provider=provider,
        llm_base_url=base_url,
        candidate_meta=candidate_meta,
        portfolio_id=build_user_live_portfolio_id(get_user_id(tool_context)),
        tg_bot_token=tg_bot_token,
        tg_chat_id=tg_chat_id,
    )
