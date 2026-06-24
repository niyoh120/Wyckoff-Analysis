"""Agent-facing AI report tools."""

from __future__ import annotations

import logging

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
        ok, reason, report_text = run_ai_report(
            symbols_info,
            provider=provider,
            api_key=api_key,
            model=model,
            base_url=base_url,
        )
        return {
            "ok": bool(ok),
            "reason": str(reason or ""),
            "report_text": str(report_text or ""),
            "model": model,
            "stock_count": len(symbols_info),
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
