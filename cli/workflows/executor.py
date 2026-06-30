"""Model-authored dynamic workflow execution runtime."""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from cli.runtime import RuntimeEvent
from cli.scratchpad import AgentScratchpad
from cli.sub_agents import (
    ANALYSIS_AGENT,
    RESEARCH_AGENT,
    TRADING_AGENT,
    WORKFLOW_TASK_AGENT,
    SubAgent,
    run_sub_agent,
)
from cli.workflows.control import WorkflowControl
from cli.workflows.models import (
    COMPLETED,
    FAILED,
    PENDING,
    RUNNING,
    STOPPED,
    WorkflowContext,
    WorkflowRun,
    WorkflowStep,
)
from cli.workflows.planner import plan_workflow
from cli.workflows.store import append_workflow_event, persist_workflow_script, save_workflow_run

_AGENTS: dict[str, SubAgent] = {
    "task": WORKFLOW_TASK_AGENT,
    "research": RESEARCH_AGENT,
    "analysis": ANALYSIS_AGENT,
    "trading": TRADING_AGENT,
}
MAX_CONCURRENT_AGENTS = 16


class WorkflowExecutor:
    """Run a model-authored workflow script by dispatching bounded sub-agents."""

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
        workflow_script: dict[str, Any] | None = None,
        source_run_id: str = "",
        workflow_args: Any = None,
        workflow_control: WorkflowControl | None = None,
        only_step_id: str = "",
    ) -> None:
        self.provider = provider
        self.tools = tools
        self.session_id = session_id
        self.user_text = user_text
        self.scratchpad = scratchpad
        self.cancel_check = cancel_check
        self.stream_chunk_timeout = stream_chunk_timeout
        self.workflow_context = workflow_context
        self.workflow_script = workflow_script
        self.source_run_id = source_run_id
        self.workflow_args = workflow_args
        self.workflow_control = workflow_control
        self.only_step_id = only_step_id
        self._stopped = False
        self.run: WorkflowRun | None = None

    def set_control(self, control: WorkflowControl | None) -> None:
        self.workflow_control = control

    def prepare_run(self) -> RuntimeEvent:
        self._plan_run(PENDING)
        return self._plan_event()

    def replace_prepared_script(self, script: dict[str, Any]) -> RuntimeEvent:
        run = self._require_run()
        old_run_id = run.run_id
        self.workflow_script = script
        self.run = plan_workflow(
            self.user_text,
            session_id=self.session_id,
            context=self.workflow_context,
            provider=self.provider,
            tools=self.tools,
            workflow_script=self.workflow_script,
            source_run_id=self.source_run_id,
            workflow_args=self.workflow_args,
            only_step_id=self.only_step_id,
        )
        self.run.run_id = old_run_id
        self.run.status = PENDING
        persist_workflow_script(self.run)
        save_workflow_run(self.run)
        payload = self._plan_event()
        append_workflow_event(old_run_id, "workflow_script_reloaded", payload)
        return payload

    def run_stream(self, messages: list[dict[str, Any]], system_prompt: str = "") -> Iterator[RuntimeEvent]:
        started_at = time.monotonic()
        if self.run is None:
            self._plan_run(RUNNING)
            yield self._plan_event()
        else:
            yield self._mark_run_running()

        results = yield from self._run_steps()
        if self._stopped:
            final_text = "workflow 已停止。已完成步骤可在 /workflow show 查看。"
            messages.append({"role": "assistant", "content": final_text})
            yield self._mark_run_stopped(final_text)
            yield {
                "type": "done",
                "text": final_text,
                "streamed": False,
                "usage": {"input_tokens": 0, "output_tokens": 0},
                "elapsed": time.monotonic() - started_at,
                "rounds": len(self._require_run().steps) + 1,
            }
            return
        final_text, usage = self._synthesize_results(results, system_prompt)
        messages.append({"role": "assistant", "content": final_text})
        if self.scratchpad:
            self.scratchpad.record_final(
                final_text,
                input_tokens=usage.get("input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0),
                elapsed_s=time.monotonic() - started_at,
            )
        yield self._mark_run_done(final_text)
        yield {
            "type": "done",
            "text": final_text,
            "streamed": False,
            "usage": usage,
            "elapsed": time.monotonic() - started_at,
            "rounds": len(self.run.steps) + 1,
        }

    def _plan_run(self, status: str) -> None:
        if self.run is not None:
            self.run.status = status
            save_workflow_run(self.run)
            return
        self.run = plan_workflow(
            self.user_text,
            session_id=self.session_id,
            context=self.workflow_context,
            provider=self.provider,
            tools=self.tools,
            workflow_script=self.workflow_script,
            source_run_id=self.source_run_id,
            workflow_args=self.workflow_args,
            only_step_id=self.only_step_id,
        )
        self.run.status = status
        persist_workflow_script(self.run)
        save_workflow_run(self.run)

    def _plan_event(self) -> RuntimeEvent:
        run = self._require_run()
        payload = {
            "type": "workflow_plan",
            "run_id": run.run_id,
            "workflow": run.workflow,
            "label": run.label,
            "route": run.context.route_payload(),
            "plan": run.plan_payload(),
        }
        append_workflow_event(run.run_id, "workflow_plan", payload)
        return payload

    def _run_steps(self) -> Iterator[RuntimeEvent | list[dict[str, Any]]]:
        results: list[dict[str, Any]] = []
        for phase_steps in _phase_batches(self._require_run().steps):
            if not self._wait_if_paused():
                self._stopped = True
                break
            yield self._phase_event("workflow_phase_start", phase_steps)
            phase_results = yield from self._run_phase(phase_steps, results)
            results.extend(phase_results)
            yield self._phase_event("workflow_phase_done", phase_steps)
            if self._cancel_requested():
                self._stopped = True
                break
        return results

    def _run_phase(
        self,
        phase_steps: list[WorkflowStep],
        prior_results: list[dict[str, Any]],
    ) -> Iterator[RuntimeEvent | list[dict[str, Any]]]:
        if len(phase_steps) == 1:
            return (yield from self._run_phase_sequential(phase_steps, prior_results))
        return (yield from self._run_phase_parallel(phase_steps, prior_results))

    def _run_phase_sequential(
        self,
        phase_steps: list[WorkflowStep],
        prior_results: list[dict[str, Any]],
    ) -> Iterator[RuntimeEvent | list[dict[str, Any]]]:
        results: list[dict[str, Any]] = []
        for step in phase_steps:
            if not self._wait_if_paused():
                self._stopped = True
                break
            yield self._mark_step_start(step)
            result = self._run_step(step, prior_results)
            results.append({"step": step.to_dict(), "result": result})
            yield self._mark_step_done(step, result)
        return results

    def _run_phase_parallel(
        self,
        phase_steps: list[WorkflowStep],
        prior_results: list[dict[str, Any]],
    ) -> Iterator[RuntimeEvent | list[dict[str, Any]]]:
        for step in phase_steps:
            yield self._mark_step_start(step)
        results: list[tuple[int, dict[str, Any]]] = []
        with ThreadPoolExecutor(max_workers=_max_workers(phase_steps), thread_name_prefix="workflow-agent") as pool:
            futures = {
                pool.submit(self._run_step, step, prior_results): (idx, step) for idx, step in enumerate(phase_steps)
            }
            for future in as_completed(futures):
                idx, step = futures[future]
                try:
                    result = future.result()
                except Exception as exc:
                    result = {"status": "error", "error": str(exc)}
                results.append((idx, {"step": step.to_dict(), "result": result}))
                yield self._mark_step_done(step, result)
        return _script_ordered_results(results)

    def _run_step(self, step: WorkflowStep, prior_results: list[dict[str, Any]]) -> dict[str, Any]:
        agent = _AGENTS.get(step.agent)
        if not agent:
            return {"status": "error", "error": f"未知 workflow agent: {step.agent}"}
        context = _step_context(step, prior_results)
        return run_sub_agent(
            agent,
            step.prompt or step.title,
            context,
            self.provider,
            self.tools,
            cancel_check=self._cancel_requested,
            tool_names=_step_tool_names(step, self._require_run().allowed_tools),
        )

    def _phase_event(self, event_type: str, phase_steps: list[WorkflowStep]) -> RuntimeEvent:
        run = self._require_run()
        phase_id = phase_steps[0].phase if phase_steps else ""
        payload = {
            "type": event_type,
            "run_id": run.run_id,
            "phase": phase_id,
            "steps": [step.to_dict() for step in phase_steps],
            "parallel": len(phase_steps) > 1,
        }
        append_workflow_event(run.run_id, event_type, payload)
        return payload

    def _mark_run_running(self) -> RuntimeEvent:
        run = self._require_run()
        run.status = RUNNING
        save_workflow_run(run)
        payload = {"type": "workflow_start", "run_id": run.run_id, "status": run.status}
        append_workflow_event(run.run_id, "workflow_start", payload)
        return payload

    def _mark_step_start(self, step: WorkflowStep) -> RuntimeEvent:
        step.status = RUNNING
        step.summary = "start"
        return self._save_step_event("workflow_step_start", step, {"type": "workflow_task_start"})

    def _mark_step_done(self, step: WorkflowStep, result: dict[str, Any]) -> RuntimeEvent:
        status = str(result.get("status", ""))
        step.status = COMPLETED if status == "completed" else FAILED
        step.summary = _brief_agent_result(result)
        return self._save_step_event(
            "workflow_step_done",
            step,
            {"type": "workflow_task_done", "status": status, "agent_detail": _agent_detail(step, result)},
        )

    def _save_step_event(self, event_type: str, step: WorkflowStep, source: RuntimeEvent) -> RuntimeEvent:
        run = self._require_run()
        run.refresh_current_step()
        save_workflow_run(run)
        payload = {
            "type": event_type,
            "run_id": run.run_id,
            "step": step.to_dict(),
            "source": _source_payload(source),
        }
        append_workflow_event(run.run_id, event_type, payload)
        return payload

    def _synthesize_results(self, results: list[dict[str, Any]], system_prompt: str) -> tuple[str, dict[str, int]]:
        prompt = _synthesis_prompt(self._require_run(), results)
        try:
            return _collect_synthesis(self.provider, prompt, system_prompt)
        except Exception:
            return _fallback_summary(results), {"input_tokens": 0, "output_tokens": 0}

    def _mark_run_done(self, final_text: str) -> RuntimeEvent:
        run = self._require_run()
        run.status = FAILED if any(step.status == FAILED for step in run.steps) else COMPLETED
        run.result_summary = final_text[:500]
        run.refresh_current_step()
        save_workflow_run(run)
        payload = {"type": "workflow_done", "run_id": run.run_id, "status": run.status}
        append_workflow_event(run.run_id, "workflow_done", payload)
        return payload

    def _mark_run_stopped(self, final_text: str) -> RuntimeEvent:
        run = self._require_run()
        run.status = STOPPED
        run.result_summary = final_text[:500]
        run.refresh_current_step()
        save_workflow_run(run)
        payload = {"type": "workflow_stopped", "run_id": run.run_id, "status": run.status}
        append_workflow_event(run.run_id, "workflow_stopped", payload)
        return payload

    def _require_run(self) -> WorkflowRun:
        if self.run is None:
            raise RuntimeError("workflow run has not been planned")
        return self.run

    def _cancel_requested(self) -> bool:
        if self.workflow_control and self.workflow_control.stopped():
            return True
        return bool(self.cancel_check and self.cancel_check())

    def _wait_if_paused(self) -> bool:
        if self.workflow_control is None:
            return not self._cancel_requested()
        return self.workflow_control.wait_if_paused() and not self._cancel_requested()


def _step_context(step: WorkflowStep, prior_results: list[dict[str, Any]]) -> str:
    lines = [f"phase={step.phase}"]
    if step.depends_on:
        lines.append(f"depends_on={', '.join(step.depends_on)}")
    if step.context:
        lines.extend(["", "task context:", step.context])
    if not prior_results:
        return "\n".join(lines)
    preview = json.dumps(prior_results[-3:], ensure_ascii=False, default=str)[:6000]
    lines.extend(["", "前序 agent 结果:", preview])
    return "\n".join(lines)


def _phase_batches(steps: list[WorkflowStep]) -> list[list[WorkflowStep]]:
    batches: list[list[WorkflowStep]] = []
    phase_steps: list[WorkflowStep] = []
    for step in steps:
        phase = step.phase or step.step_id
        if not phase_steps or (phase_steps[-1].phase or phase_steps[-1].step_id) == phase:
            phase_steps.append(step)
        else:
            batches.extend(_dependency_batches(phase_steps))
            phase_steps = [step]
    if phase_steps:
        batches.extend(_dependency_batches(phase_steps))
    return batches


def _dependency_batches(steps: list[WorkflowStep]) -> list[list[WorkflowStep]]:
    batches: list[list[WorkflowStep]] = []
    remaining = list(steps)
    completed_ids: set[str] = set()
    phase_ids = {step.step_id for step in steps}
    while remaining:
        ready = [step for step in remaining if _phase_dependencies(step, phase_ids).issubset(completed_ids)]
        if not ready:
            batches.extend([step] for step in remaining)
            break
        batches.append(ready)
        completed_ids.update(step.step_id for step in ready)
        ready_ids = {id(step) for step in ready}
        remaining = [step for step in remaining if id(step) not in ready_ids]
    return batches


def _phase_dependencies(step: WorkflowStep, phase_ids: set[str]) -> set[str]:
    return {dep for dep in step.depends_on if dep in phase_ids}


def _script_ordered_results(results: list[tuple[int, dict[str, Any]]]) -> list[dict[str, Any]]:
    return [item for _idx, item in sorted(results, key=lambda pair: pair[0])]


def _step_tool_names(step: WorkflowStep, allowed_tools: tuple[str, ...]) -> tuple[str, ...] | None:
    allowed = _concrete_tools(allowed_tools)
    if not allowed:
        return step.tool_scope or None
    scope = tuple(name for name in (step.tool_scope or allowed) if name in allowed)
    return scope or None


def _concrete_tools(names: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(name for name in names if name and not name.startswith("delegate_to_"))


def _max_workers(steps: list[WorkflowStep]) -> int:
    return max(1, min(len(steps), MAX_CONCURRENT_AGENTS))


def _brief_agent_result(result: dict[str, Any]) -> str:
    status = str(result.get("status", ""))
    elapsed = float(result.get("elapsed", 0.0))
    if result.get("error"):
        return f"{status} {str(result['error'])[:100]}"
    return f"{status} {elapsed:.1f}s"


def _source_payload(event: RuntimeEvent) -> dict[str, Any]:
    payload = {
        "type": event.get("type", ""),
        "name": event.get("name", ""),
        "status": event.get("status", ""),
        "elapsed_ms": event.get("elapsed_ms", 0),
        "error": event.get("error", ""),
    }
    if event.get("agent_detail"):
        payload["agent_detail"] = event["agent_detail"]
    return payload


def _agent_detail(step: WorkflowStep, result: dict[str, Any]) -> dict[str, Any]:
    return {
        "step_id": step.step_id,
        "title": step.title,
        "agent": step.agent,
        "phase": step.phase,
        "prompt": _clip(step.prompt, 4000),
        "context": _clip(step.context, 4000),
        "tool_scope": list(step.tool_scope),
        "status": str(result.get("status", "")),
        "elapsed": result.get("elapsed", 0),
        "tool_calls": list(result.get("tool_calls", []) or [])[:40],
        "result": _clip(str(result.get("result", "") or ""), 8000),
        "error": _clip(str(result.get("error", "") or ""), 2000),
    }


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "..."


def _synthesis_prompt(run: WorkflowRun, results: list[dict[str, Any]]) -> str:
    script_prompt = ""
    if isinstance(run.script, dict):
        script_prompt = str(run.script.get("synthesis_prompt", "") or "").strip()
    return (
        "请基于以下动态 workflow 执行结果，给用户输出最终中文答复。\n"
        "要求：只使用 agent 结果里的事实；如果某步失败，明确说明影响和降级结论。\n\n"
        f"模型脚本的汇总要求:\n{script_prompt or '-'}\n\n"
        f"用户请求:\n{run.user_text}\n\n"
        f"workflow script:\n{json.dumps(run.script, ensure_ascii=False, default=str)[:4000]}\n\n"
        f"agent results:\n{json.dumps(results, ensure_ascii=False, default=str)[:12000]}"
    )


def _collect_synthesis(provider: Any, prompt: str, system_prompt: str) -> tuple[str, dict[str, int]]:
    text_parts: list[str] = []
    usage = {"input_tokens": 0, "output_tokens": 0}
    for chunk in provider.chat_stream([{"role": "user", "content": prompt}], [], system_prompt):
        if chunk.get("type") == "text_delta":
            text_parts.append(str(chunk.get("text", "")))
        elif chunk.get("type") == "usage":
            usage["input_tokens"] += int(chunk.get("input_tokens", 0) or 0)
            usage["output_tokens"] += int(chunk.get("output_tokens", 0) or 0)
    text = "".join(text_parts).strip()
    return (text or _fallback_summary([]), usage)


def _fallback_summary(results: list[dict[str, Any]]) -> str:
    lines = ["动态 workflow 已完成，以下是各 sub-agent 的结果摘要："]
    for item in results:
        step = item.get("step", {})
        result = item.get("result", {})
        title = step.get("title", "任务")
        status = result.get("status", "unknown")
        content = result.get("result") or result.get("error") or "无结果"
        lines.append(f"- {title} [{status}]: {str(content)[:500]}")
    return "\n".join(lines)
