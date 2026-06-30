"""Agent-facing AI report tools."""

from __future__ import annotations

import logging
import re
from typing import Any

from agents.stock_data_helpers import code_to_name
from agents.tool_context import ToolContext, ensure_tushare_token, resolve_llm_config

logger = logging.getLogger(__name__)

_CN_CODE_RE = re.compile(r"(?i)^(?:SH|SZ|BJ)?\.?([0134568]\d{5})(?:\.(?:SH|SZ|BJ))?$")
_CN_CODE_TOKEN_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9])(?:SH|SZ|BJ)?\.?([0134568]\d{5})(?:\.(?:SH|SZ|BJ))?(?![A-Za-z0-9])"
)


def generate_ai_report(stock_codes: Any = None, tool_context: ToolContext | None = None) -> dict:
    """对指定股票列表生成威科夫三阵营 AI 深度研报。"""
    try:
        ensure_tushare_token(tool_context)
        stock_items = _stock_items_or_screen_handoff(stock_codes, tool_context)
        if not stock_items:
            return {"error": "请提供至少一个股票代码"}
        provider, api_key, model, base_url = resolve_llm_config(tool_context)
        if not api_key:
            return {"error": "未配置 LLM API Key，无法生成 AI 研报。请通过 /model 或设置页面配置。"}
        symbols_info = symbols_info_from_codes(stock_items[:10], tool_context)
        if not symbols_info:
            return {"error": "请提供至少一个有效股票代码"}
        ok, reason, report_text = run_ai_report(
            symbols_info,
            provider=provider,
            api_key=api_key,
            model=model,
            base_url=base_url,
        )
        ok_bool = bool(ok)
        reviewed_symbols = reviewed_symbols_from_info(symbols_info)
        result = {
            "ok": ok_bool,
            "reason": str(reason or ""),
            "report_text": str(report_text or ""),
            "model": model,
            "stock_count": len(symbols_info),
            "reviewed_codes": [row["code"] for row in reviewed_symbols],
            "reviewed_symbols": reviewed_symbols,
            "next_action": report_next_action(ok_bool),
            "next_tool": report_next_tool(ok_bool),
        }
        remember_ai_report(tool_context, result)
        return result
    except Exception as e:
        logger.exception("generate_ai_report error")
        return {"error": str(e)}


def symbols_info_from_codes(stock_codes: Any, tool_context: ToolContext | None = None) -> list[dict]:
    screen_symbols = screen_symbol_map(tool_context)
    stock_codes = _stock_code_items(stock_codes)
    rows: list[dict] = []
    seen: set[str] = set()
    for item in stock_codes:
        code = _candidate_code(item)
        if not code:
            continue
        row = dict(screen_symbols.get(code) or {})
        if isinstance(item, dict):
            row.update({key: value for key, value in item.items() if _has_value(value)})
        row["code"] = code
        row["name"] = str(row.get("name") or code_to_name(code)).strip()
        row["tag"] = str(row.get("tag") or "chat_request").strip()
        if code in seen:
            continue
        seen.add(code)
        rows.append(row)
    return rows


def _stock_items_or_screen_handoff(stock_codes: Any, tool_context: ToolContext | None) -> list[Any]:
    return _stock_code_items(stock_codes) or _screen_handoff_stock_items(tool_context)


def _screen_handoff_stock_items(tool_context: ToolContext | None) -> list[Any]:
    screen_result = _last_screen_result(tool_context)
    if not screen_result:
        return []
    for value in _screen_handoff_sources(screen_result):
        items = _stock_code_items(value)
        if items:
            return items
    return []


def _screen_handoff_sources(screen_result: dict[str, Any]) -> list[Any]:
    selection = screen_result.get("selection_brief") if isinstance(screen_result.get("selection_brief"), dict) else {}
    action_plan = screen_result.get("action_plan") if isinstance(screen_result.get("action_plan"), dict) else {}
    review_targets = action_plan.get("review_targets") if isinstance(action_plan.get("review_targets"), dict) else {}
    return [
        _tool_handoff_stock_codes(selection.get("tool_handoff")),
        _tool_handoff_stock_codes(review_targets),
        review_targets.get("codes"),
        screen_result.get("symbols_for_report"),
        selection.get("best_candidates"),
        selection.get("best_codes"),
        screen_result.get("top_candidates"),
    ]


def _tool_handoff_stock_codes(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return []
    args = payload.get("args")
    if isinstance(args, dict) and args.get("stock_codes"):
        return args["stock_codes"]
    return []


def _stock_code_items(value: Any) -> list[Any]:
    if value in (None, ""):
        return []
    items = list(value) if isinstance(value, (list, tuple, set)) else [value]
    out: list[Any] = []
    for item in items:
        if isinstance(item, str):
            codes = _stock_codes_from_text(item)
            out.extend(codes or (part for part in re.split(r"[,，、\n]+", item) if part.strip()))
        else:
            out.append(item)
    return out


def _candidate_code(item: Any) -> str:
    if isinstance(item, dict):
        return normalize_stock_code(item.get("code") or item.get("symbol"))
    return normalize_stock_code(item)


def normalize_stock_code(raw: Any) -> str:
    text = str(raw or "").strip()
    match = _CN_CODE_RE.fullmatch(text)
    return match.group(1) if match else text


def _stock_codes_from_text(text: str) -> list[str]:
    codes = _CN_CODE_TOKEN_RE.findall(str(text or ""))
    return list(dict.fromkeys(codes))


def _last_screen_result(tool_context: ToolContext | None) -> dict[str, Any]:
    value = tool_context.state.get("last_screen_result") if tool_context else {}
    return value if isinstance(value, dict) else {}


def reviewed_symbols_from_info(symbols_info: list[dict]) -> list[dict]:
    return [symbol for row in symbols_info if (symbol := _compact_symbol(row)).get("code")]


def _compact_symbol(row: dict[str, Any]) -> dict:
    payload = {field: _compact_symbol_value(row.get(field)) for field in _COMPACT_SYMBOL_FIELDS}
    payload["code"] = normalize_stock_code(row.get("code") or row.get("symbol"))
    return {key: value for key, value in payload.items() if value}


def screen_symbol_map(tool_context: ToolContext | None) -> dict[str, dict]:
    if tool_context is None:
        return {}
    screen_result = tool_context.state.get("last_screen_result")
    if not isinstance(screen_result, dict):
        return {}
    symbols: dict[str, dict] = {}
    for row in _screen_symbol_rows(screen_result):
        code = _candidate_code(row)
        if not code or not isinstance(row, dict):
            continue
        symbols.setdefault(code, {}).update({key: value for key, value in row.items() if _has_value(value)})
    return symbols


def _screen_symbol_rows(screen_result: dict[str, Any]) -> list[Any]:
    rows = list(screen_result.get("symbols_for_report") or []) + list(screen_result.get("top_candidates") or [])
    selection_brief = screen_result.get("selection_brief")
    if isinstance(selection_brief, dict) and isinstance(selection_brief.get("best_candidates"), list):
        rows.extend(selection_brief["best_candidates"])
    return rows


def _has_value(value: Any) -> bool:
    return value is not None and value != "" and value != [] and value != {}


def remember_ai_report(tool_context: ToolContext | None, result: dict[str, Any]) -> None:
    if tool_context is not None:
        tool_context.state["last_ai_report"] = result


def _compact_symbol_value(value: Any) -> Any:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float, bool)):
        return value
    text = str(value).strip()
    return text or None


def report_next_action(ok: bool) -> str:
    if ok:
        return "研报已完成，可结合持仓和候选进入组合攻防决策"
    return "研报未成功生成，先处理失败原因后再继续复核"


def report_next_tool(ok: bool) -> dict:
    if not ok:
        return {}
    return {
        "tool": "generate_strategy_decision",
        "args": {},
        "reason": "研报已完成，可继续生成持仓去留和新标的攻防计划",
    }


_COMPACT_SYMBOL_FIELDS = (
    "code",
    "name",
    "tag",
    "track",
    "stage",
    "candidate_lane",
    "entry_type",
    "selection_source",
    "source_type",
    "priority_rank",
    "priority_score",
    "score",
    "rank_reason",
    "tier",
    "quality",
    "why",
    "evidence",
    "next_step",
    "capital_migration_bonus",
    "industry",
    "sector",
)


def run_ai_report(
    symbols_info: list[dict],
    *,
    provider: str,
    api_key: str,
    model: str,
    base_url: str,
) -> tuple[bool, str, str]:
    from workflows.step3_batch_report import run as run_step3

    return run_step3(
        symbols_info,
        webhook_url="",
        api_key=api_key,
        model=model,
        benchmark_context=None,
        notify=False,
        provider=provider,
        llm_base_url=base_url,
    )
