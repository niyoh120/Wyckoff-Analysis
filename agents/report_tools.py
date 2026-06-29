"""Agent-facing AI report tools."""

from __future__ import annotations

import logging
from typing import Any

from agents.stock_data_helpers import code_to_name
from agents.tool_context import ToolContext, ensure_tushare_token, resolve_llm_config

logger = logging.getLogger(__name__)


def generate_ai_report(stock_codes: list[str], tool_context: ToolContext | None = None) -> dict:
    """对指定股票列表生成威科夫三阵营 AI 深度研报。"""
    try:
        ensure_tushare_token(tool_context)
        if not stock_codes:
            return {"error": "请提供至少一个股票代码"}
        provider, api_key, model, base_url = resolve_llm_config(tool_context)
        if not api_key:
            return {"error": "未配置 LLM API Key，无法生成 AI 研报。请通过 /model 或设置页面配置。"}
        symbols_info = symbols_info_from_codes(stock_codes[:10])
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
        return {
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
    except Exception as e:
        logger.exception("generate_ai_report error")
        return {"error": str(e)}


def symbols_info_from_codes(stock_codes: list[str]) -> list[dict]:
    return [
        {"code": code, "name": code_to_name(code), "tag": "chat_request"}
        for code in [str(code).strip() for code in stock_codes]
        if code
    ]


def reviewed_symbols_from_info(symbols_info: list[dict]) -> list[dict]:
    return [symbol for row in symbols_info if (symbol := _compact_symbol(row)).get("code")]


def _compact_symbol(row: dict[str, Any]) -> dict:
    payload = {
        "code": str(row.get("code") or row.get("symbol") or "").strip(),
        "name": str(row.get("name") or "").strip(),
        "tag": str(row.get("tag") or "").strip(),
    }
    return {key: value for key, value in payload.items() if value}


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
