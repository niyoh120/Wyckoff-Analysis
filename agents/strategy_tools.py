"""Agent-facing portfolio strategy decision tool."""

from __future__ import annotations

import logging

from agents.report_tools import run_ai_report
from agents.screen_tools import screen_stocks
from agents.tool_context import ToolContext, ensure_tushare_token, get_credential, get_user_id, resolve_llm_config

logger = logging.getLogger(__name__)


def generate_strategy_decision(tool_context: ToolContext | None = None) -> dict:
    """生成持仓去留决策和新标的买入策略。"""
    try:
        ensure_tushare_token(tool_context)
        provider, api_key, model, base_url = resolve_llm_config(tool_context)
        if not api_key:
            return {"error": "未配置 LLM API Key，无法生成策略决策。请通过 /model 或设置页面配置。"}

        screen_result = screen_stocks(board="all", tool_context=tool_context)
        if screen_result.get("error"):
            return {"error": f"筛选失败: {screen_result['error']}"}

        report_text = _report_for_screen_result(screen_result, provider, api_key, model, base_url)
        token = get_credential(tool_context, "tg_bot_token", "TG_BOT_TOKEN")
        chat_id = get_credential(tool_context, "tg_chat_id", "TG_CHAT_ID")
        if not token or not chat_id:
            return _strategy_without_telegram(screen_result, report_text)
        ok, reason = _run_strategy_step4(
            tool_context,
            report_text,
            provider,
            api_key,
            model,
            base_url,
            token,
            chat_id,
        )
        return {"ok": bool(ok), "reason": str(reason or ""), "screen_summary": screen_result.get("summary", {})}
    except Exception as e:
        logger.exception("generate_strategy_decision error")
        return {"error": str(e)}


def _report_for_screen_result(screen_result: dict, provider: str, api_key: str, model: str, base_url: str) -> str:
    symbols_info = screen_result.get("symbols_for_report", [])
    if not symbols_info:
        return ""
    _ok, _reason, report_text = run_ai_report(
        symbols_info,
        provider=provider,
        api_key=api_key,
        model=model,
        base_url=base_url,
    )
    return str(report_text or "")


def _strategy_without_telegram(screen_result: dict, report_text: str) -> dict:
    return {
        "message": "策略分析完成，但未配置 Telegram，OMS 交易工单不会发送。以下是筛选和研报结果。",
        "screen_summary": screen_result.get("summary", {}),
        "report_preview": (report_text[:2000] + "...") if len(report_text) > 2000 else report_text,
    }


def _run_strategy_step4(
    tool_context: ToolContext | None,
    report_text: str,
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
        portfolio_id=build_user_live_portfolio_id(get_user_id(tool_context)),
        tg_bot_token=tg_bot_token,
        tg_chat_id=tg_chat_id,
    )
