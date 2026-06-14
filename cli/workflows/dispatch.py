"""Runtime selection for natural-language turns."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from cli.runtime import AgentRuntime
from cli.scratchpad import AgentScratchpad
from cli.workflows.executor import WorkflowExecutor
from cli.workflows.models import WorkflowContext
from cli.workflows.router import route_workflow


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
) -> tuple[Any, WorkflowContext]:
    """Return direct runtime for general chat, workflow executor for task turns."""

    workflow = workflow_context or route_workflow(user_text)
    if workflow.is_general:
        kwargs: dict[str, Any] = {"scratchpad": scratchpad, "cancel_check": cancel_check}
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
        ),
        workflow,
    )
