"""Dynamic workflow execution wrapper around AgentRuntime."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

from cli.runtime import AgentRuntime, RuntimeEvent
from cli.scratchpad import AgentScratchpad
from cli.workflows.models import COMPLETED, FAILED, PENDING, RUNNING, SKIPPED, WorkflowContext, WorkflowStep
from cli.workflows.planner import plan_workflow
from cli.workflows.store import append_workflow_event, save_workflow_run


class WorkflowExecutor:
    """Plan, run, track, and persist one dynamic workflow turn."""

    def __init__(
        self,
        provider,
        tools,
        *,
        session_id: str,
        user_text: str,
        scratchpad: AgentScratchpad | None = None,
        cancel_check: Callable[[], bool] | None = None,
        stream_chunk_timeout: float | None = None,
        workflow_context: WorkflowContext | None = None,
    ) -> None:
        self.run = plan_workflow(user_text, session_id=session_id, context=workflow_context)
        self.provider = provider
        self.tools = tools
        self.scratchpad = scratchpad
        self.cancel_check = cancel_check
        self.stream_chunk_timeout = stream_chunk_timeout
        self._last_step_id = ""

    def run_stream(self, messages: list[dict[str, Any]], system_prompt: str = "") -> Iterator[RuntimeEvent]:
        save_workflow_run(self.run)
        yield self._plan_event()
        runtime = self._runtime()
        for event in runtime.run_stream(messages, system_prompt):
            yield from self._workflow_updates(event)
            yield event

    def _runtime(self) -> AgentRuntime:
        kwargs: dict[str, Any] = {
            "scratchpad": self.scratchpad,
            "cancel_check": self.cancel_check,
            "workflow": self.run.context,
        }
        if self.stream_chunk_timeout is not None:
            kwargs["stream_chunk_timeout"] = self.stream_chunk_timeout
        return AgentRuntime(self.provider, self.tools, **kwargs)

    def _plan_event(self) -> RuntimeEvent:
        payload = {
            "type": "workflow_plan",
            "run_id": self.run.run_id,
            "workflow": self.run.workflow,
            "label": self.run.label,
            "plan": self.run.plan_payload(),
        }
        append_workflow_event(self.run.run_id, "workflow_plan", payload)
        return payload

    def _workflow_updates(self, event: RuntimeEvent) -> Iterator[RuntimeEvent]:
        event_type = event.get("type")
        if event_type == "tool_start":
            yield self._mark_tool_start(event)
        elif event_type in {"tool_result", "tool_error"}:
            yield self._mark_tool_done(event, failed=event_type == "tool_error")
        elif event_type == "done":
            yield self._mark_run_done(event)

    def _mark_tool_start(self, event: RuntimeEvent) -> RuntimeEvent:
        step = self._step_for_tool(str(event.get("name", "")))
        step.status = RUNNING
        step.summary = _brief_tool_event(event)
        self._last_step_id = step.step_id
        return self._save_step_event("workflow_step_start", step, event)

    def _mark_tool_done(self, event: RuntimeEvent, *, failed: bool) -> RuntimeEvent:
        step = self._active_step(str(event.get("name", "")))
        step.status = FAILED if failed else COMPLETED
        step.summary = _brief_tool_event(event)
        return self._save_step_event("workflow_step_done", step, event)

    def _mark_run_done(self, event: RuntimeEvent) -> RuntimeEvent:
        self._skip_pending_steps()
        self.run.status = COMPLETED
        self.run.result_summary = str(event.get("text", ""))[:500]
        self.run.refresh_current_step()
        save_workflow_run(self.run)
        payload = {"type": "workflow_done", "run_id": self.run.run_id, "status": self.run.status}
        append_workflow_event(self.run.run_id, "workflow_done", payload)
        return payload

    def _save_step_event(self, event_type: str, step: WorkflowStep, source: RuntimeEvent) -> RuntimeEvent:
        self.run.refresh_current_step()
        save_workflow_run(self.run)
        payload = {
            "type": event_type,
            "run_id": self.run.run_id,
            "step": step.to_dict(),
            "source": _source_payload(source),
        }
        append_workflow_event(self.run.run_id, event_type, payload)
        return payload

    def _step_for_tool(self, tool_name: str) -> WorkflowStep:
        for step in self.run.steps:
            if step.status not in {COMPLETED, FAILED, SKIPPED} and tool_name in step.tools:
                return step
        return self._append_dynamic_step(tool_name)

    def _active_step(self, tool_name: str) -> WorkflowStep:
        for step in self.run.steps:
            if step.status == RUNNING and (tool_name in step.tools or step.step_id == self._last_step_id):
                return step
        return self._step_for_tool(tool_name)

    def _append_dynamic_step(self, tool_name: str) -> WorkflowStep:
        step = WorkflowStep(
            step_id=f"dynamic_{len(self.run.steps) + 1}",
            title=f"动态执行工具 {tool_name}",
            tools=(tool_name,),
            dynamic=True,
        )
        self.run.steps.append(step)
        return step

    def _skip_pending_steps(self) -> None:
        for step in self.run.steps:
            if step.status == PENDING:
                step.status = SKIPPED


def _brief_tool_event(event: RuntimeEvent) -> str:
    name = str(event.get("name", ""))
    status = str(event.get("status", ""))
    if event.get("error"):
        return f"{name}: {str(event['error'])[:120]}"
    return f"{name}: {status or event.get('type', '')}"


def _source_payload(event: RuntimeEvent) -> dict[str, Any]:
    return {
        "type": event.get("type", ""),
        "name": event.get("name", ""),
        "status": event.get("status", ""),
        "elapsed_ms": event.get("elapsed_ms", 0),
        "error": event.get("error", ""),
    }
