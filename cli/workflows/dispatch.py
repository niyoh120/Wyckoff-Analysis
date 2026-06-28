"""Runtime selection for natural-language turns."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from cli.runtime import AgentRuntime
from cli.scratchpad import AgentScratchpad
from cli.workflows.executor import WorkflowExecutor
from cli.workflows.models import WorkflowContext
from cli.workflows.router import route_workflow

_DIRECT_TOOL_ORDER = (
    "search_stock_by_name",
    "analyze_stock",
    "portfolio",
    "get_market_overview",
    "get_market_history",
    "screen_stocks",
    "generate_ai_report",
    "generate_strategy_decision",
    "query_history",
    "update_portfolio",
    "run_backtest",
    "check_background_tasks",
    "ask_user_question",
    "delegate_to_research",
    "delegate_to_analysis",
    "delegate_to_trading",
    "read_file",
    "write_file",
    "web_fetch",
    "exec_command",
)
_LOCAL_TOOLS = {"read_file", "write_file", "web_fetch", "exec_command"}
_SAFE_DIRECT_TOOLS = frozenset(tool for tool in _DIRECT_TOOL_ORDER if tool not in _LOCAL_TOOLS)
_WEB_FETCH_MARKERS = ("http://", "https://", "网页", "链接", "url", "公告", "新闻", "抓取")
_READ_FILE_MARKERS = ("读取文件", "读文件", "打开文件", ".csv", ".xlsx", ".xls", ".json", ".md")
_WRITE_FILE_MARKERS = ("写入文件", "写文件", "导出", "保存到", "生成文件")
_COMMAND_MARKERS = ("执行命令", "运行命令", "shell", "终端命令")


def build_turn_runtime(
    provider: Any,
    tools: Any,
    *,
    session_id: str,
    user_text: str,
    scratchpad: AgentScratchpad | None = None,
    cancel_check: Callable[[], bool] | None = None,
    stream_chunk_timeout: float | None = None,
    workflow_context: WorkflowContext | None = None,
    workflow_script: dict[str, Any] | None = None,
    workflow_source_run_id: str = "",
    workflow_args: Any = None,
    workflow_only_step_id: str = "",
) -> tuple[Any, WorkflowContext]:
    """Return direct runtime for general chat, workflow executor for task turns."""

    workflow = workflow_context or route_workflow(user_text)
    if workflow.is_general and not workflow_script:
        kwargs: dict[str, Any] = {
            "scratchpad": scratchpad,
            "cancel_check": cancel_check,
            "allowed_tools": infer_direct_allowed_tools(user_text),
        }
        if stream_chunk_timeout is not None:
            kwargs["stream_chunk_timeout"] = stream_chunk_timeout
        return AgentRuntime(provider, tools, **kwargs), workflow
    return (
        WorkflowExecutor(
            provider,
            tools,
            session_id=session_id,
            user_text=user_text,
            scratchpad=scratchpad,
            cancel_check=cancel_check,
            stream_chunk_timeout=stream_chunk_timeout,
            workflow_context=workflow,
            workflow_script=workflow_script,
            source_run_id=workflow_source_run_id,
            workflow_args=workflow_args,
            only_step_id=workflow_only_step_id,
        ),
        workflow,
    )


def infer_direct_allowed_tools(user_text: str) -> tuple[str, ...]:
    """Limit local tools in direct chat unless the user clearly asks for them."""

    text = str(user_text or "").lower()
    allowed = set(_SAFE_DIRECT_TOOLS)
    if _has_any(text, _WEB_FETCH_MARKERS):
        allowed.add("web_fetch")
    if _has_any(text, _READ_FILE_MARKERS):
        allowed.add("read_file")
    if _has_any(text, _WRITE_FILE_MARKERS):
        allowed.update(("read_file", "write_file"))
    if _has_any(text, _COMMAND_MARKERS):
        allowed.add("exec_command")
    return tuple(tool for tool in _DIRECT_TOOL_ORDER if tool in allowed)


def _has_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)
