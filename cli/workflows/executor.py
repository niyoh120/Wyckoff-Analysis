"""Model-authored dynamic workflow execution runtime."""

from __future__ import annotations

import json
import os
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
from core.candidate_guards import candidate_guard_reason
from utils.tool_result_preview import tool_result_brief_lines

_AGENTS: dict[str, SubAgent] = {
    "task": WORKFLOW_TASK_AGENT,
    "research": RESEARCH_AGENT,
    "analysis": ANALYSIS_AGENT,
    "trading": TRADING_AGENT,
}
_TURN_EXPECTATION_TOOL_SCOPES = frozenset(
    {
        "portfolio",
        "get_market_overview",
        "screen_stocks",
        "generate_ai_report",
        "generate_strategy_decision",
        "run_backtest",
    }
)
MAX_CONCURRENT_AGENTS = 16
WORKFLOW_BACKGROUND_WAIT_SECONDS = 45.0
_SYNTHESIS_REQUIREMENTS = (
    "输出要求：\n"
    "- 先给结论和可执行下一步，不要只复述 workflow 步骤。\n"
    "- 如果 agent results 里有候选、policy_selection、last_screen_result 或 last_recommendation_event_eval，"
    "必须按候选分层输出：可进入 AI 研报/攻防决策、仅观察、被数据质量/市场闸门/策略保护阻断。\n"
    "- 候选行要优先使用代码/名称、action_status、trade_readiness、priority_score/shadow_score/"
    "funnel_score、candidate_shadow_score/grade、candidate_quality_score、risk_adjusted_quality_score、"
    "entry_quality_score/grade、entry_quality_risk_flags、quality_factors、risk_factors、next_step。\n"
    "- 如果存在 candidate_guard_summary，必须明确哪些候选禁止直接买入以及原因；"
    "如果 new_buy_allowed=false、trade_readiness=research_only 或 action_status 不是可执行状态，"
    "不得写成买入建议；只能写观察、研报复核或攻防决策下一步。\n"
    "- 如果没有可靠候选或数据质量不足，说明不能选出股票的原因和修复动作。\n"
)


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
            results.append({"step": self._step_payload(step), "result": result})
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
                results.append((idx, {"step": self._step_payload(step), "result": result}))
                yield self._mark_step_done(step, result)
        return _script_ordered_results(results)

    def _run_step(self, step: WorkflowStep, prior_results: list[dict[str, Any]]) -> dict[str, Any]:
        agent = _AGENTS.get(step.agent)
        if not agent:
            return {"status": "error", "error": f"未知 workflow agent: {step.agent}"}
        context = _step_context(step, prior_results)
        result = run_sub_agent(
            agent,
            step.prompt or step.title,
            context,
            self.provider,
            self.tools,
            cancel_check=self._cancel_requested,
            tool_names=_step_tool_names(step, self._require_run().allowed_tools),
            enforce_turn_expectations=_step_turn_expectations_enabled(step),
            required_tool_names=_step_required_tool_names(step),
        )
        if wait_result := _wait_step_background_tasks(self.tools, result.get("background_task_ids") or []):
            result["background_tasks"] = wait_result
        if handoff_state := _workflow_handoff_state(self.tools):
            result["handoff_state"] = handoff_state
        return result

    def _phase_event(self, event_type: str, phase_steps: list[WorkflowStep]) -> RuntimeEvent:
        run = self._require_run()
        phase_id = _batch_phase_id(phase_steps)
        payload = {
            "type": event_type,
            "run_id": run.run_id,
            "phase": phase_id,
            "steps": [run.step_payload(step) for step in phase_steps],
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
            "step": run.step_payload(step),
            "source": _source_payload(source),
        }
        append_workflow_event(run.run_id, event_type, payload)
        return payload

    def _step_payload(self, step: WorkflowStep) -> dict[str, Any]:
        return self._require_run().step_payload(step)

    def _synthesize_results(self, results: list[dict[str, Any]], system_prompt: str) -> tuple[str, dict[str, int]]:
        prompt = _synthesis_prompt(self._require_run(), results)
        fallback_text = _fallback_summary(results)
        try:
            return _collect_synthesis(self.provider, prompt, system_prompt, fallback_text=fallback_text)
        except Exception:
            return fallback_text, {"input_tokens": 0, "output_tokens": 0}

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
    if step.rationale:
        lines.extend(["", "task rationale:", step.rationale])
    if step.success_criteria:
        lines.extend(["", "success criteria:", step.success_criteria])
    if step.risk_guard:
        lines.extend(["", "risk guard:", step.risk_guard])
    if step.context:
        lines.extend(["", "task context:", step.context])
    if not prior_results:
        return "\n".join(lines)
    preview = json.dumps(prior_results[-3:], ensure_ascii=False, default=str)[:6000]
    lines.extend(["", "前序 agent 结果:", preview])
    return "\n".join(lines)


def _phase_batches(steps: list[WorkflowStep]) -> list[list[WorkflowStep]]:
    if _has_cross_phase_dependencies(steps):
        return _dependency_batches(steps)
    batches: list[list[WorkflowStep]] = []
    phase_steps: list[WorkflowStep] = []
    for step in steps:
        phase = _step_phase_id(step)
        if not phase_steps or _step_phase_id(phase_steps[-1]) == phase:
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
    step_ids = {step.step_id for step in steps}
    while remaining:
        ready = [step for step in remaining if _known_dependencies(step, step_ids).issubset(completed_ids)]
        if not ready:
            batches.extend([step] for step in remaining)
            break
        batches.append(ready)
        completed_ids.update(step.step_id for step in ready)
        ready_ids = {id(step) for step in ready}
        remaining = [step for step in remaining if id(step) not in ready_ids]
    return batches


def _has_cross_phase_dependencies(steps: list[WorkflowStep]) -> bool:
    phase_by_step_id = {step.step_id: _step_phase_id(step) for step in steps}
    return any(
        dep in phase_by_step_id and phase_by_step_id[dep] != _step_phase_id(step)
        for step in steps
        for dep in step.depends_on
    )


def _known_dependencies(step: WorkflowStep, step_ids: set[str]) -> set[str]:
    return {dep for dep in step.depends_on if dep in step_ids}


def _batch_phase_id(phase_steps: list[WorkflowStep]) -> str:
    if not phase_steps:
        return ""
    phase_ids = [_step_phase_id(step) for step in phase_steps]
    return phase_ids[0] if len(set(phase_ids)) == 1 else "mixed"


def _step_phase_id(step: WorkflowStep) -> str:
    return step.phase or step.step_id


def _script_ordered_results(results: list[tuple[int, dict[str, Any]]]) -> list[dict[str, Any]]:
    return [item for _idx, item in sorted(results, key=lambda pair: pair[0])]


def _step_tool_names(step: WorkflowStep, allowed_tools: tuple[str, ...]) -> tuple[str, ...] | None:
    allowed = _concrete_tools(allowed_tools)
    if not allowed:
        return step.tool_scope or None
    if step.tool_scope:
        return tuple(name for name in step.tool_scope if name in allowed)
    return allowed


def _step_turn_expectations_enabled(step: WorkflowStep) -> bool:
    return bool(set(step.tool_scope).intersection(_TURN_EXPECTATION_TOOL_SCOPES))


def _step_required_tool_names(step: WorkflowStep) -> tuple[str, ...]:
    return tuple(name for name in _concrete_tools(step.tool_scope) if name in _TURN_EXPECTATION_TOOL_SCOPES)


def _concrete_tools(names: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(name for name in names if name and not name.startswith("delegate_to_"))


def _max_workers(steps: list[WorkflowStep]) -> int:
    return max(1, min(len(steps), MAX_CONCURRENT_AGENTS))


def _brief_agent_result(result: dict[str, Any]) -> str:
    status = str(result.get("status", ""))
    elapsed = float(result.get("elapsed", 0.0))
    if result.get("error"):
        return f"{status} {str(result['error'])[:100]}"
    if background := _brief_background_result(result.get("background_tasks")):
        return f"{status} {elapsed:.1f}s {background}"
    return f"{status} {elapsed:.1f}s"


def _brief_background_result(tasks: Any) -> str:
    for task in _as_list(tasks):
        if not isinstance(task, dict):
            continue
        if summary := _clip_text(task.get("result_summary"), 160):
            name = str(task.get("tool_name") or task.get("task_id") or "background").strip()
            return f"{name}: {summary}"
        if task.get("status") == "failed" and task.get("error"):
            return f"{task.get('tool_name') or 'background'} failed: {_clip_text(task.get('error'), 120)}"
    return ""


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
        "rationale": _clip(step.rationale, 1000),
        "success_criteria": _clip(step.success_criteria, 1000),
        "risk_guard": _clip(step.risk_guard, 1000),
        "tool_scope": list(step.tool_scope),
        "status": str(result.get("status", "")),
        "elapsed": result.get("elapsed", 0),
        "tool_calls": list(result.get("tool_calls", []) or [])[:40],
        "background_task_ids": list(result.get("background_task_ids", []) or [])[:20],
        "background_tasks": list(result.get("background_tasks", []) or [])[:20],
        "handoff_state": result.get("handoff_state", {}),
        "result": _clip(str(result.get("result", "") or ""), 8000),
        "error": _clip(str(result.get("error", "") or ""), 2000),
    }


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "..."


def _wait_step_background_tasks(tools: Any, task_ids: list[str]) -> list[dict[str, Any]]:
    ids = [str(task_id).strip() for task_id in task_ids if str(task_id).strip()]
    if not ids or not hasattr(tools, "wait_background_tasks"):
        return []
    return tools.wait_background_tasks(ids, timeout_seconds=_workflow_background_wait_seconds())


def _workflow_background_wait_seconds() -> float:
    raw = os.getenv("WYCKOFF_WORKFLOW_BG_WAIT_SECONDS", "").strip()
    if not raw:
        return WORKFLOW_BACKGROUND_WAIT_SECONDS
    try:
        return max(float(raw), 0.0)
    except ValueError:
        return WORKFLOW_BACKGROUND_WAIT_SECONDS


def _workflow_handoff_state(tools: Any) -> dict[str, Any]:
    context = getattr(tools, "_tool_context", None)
    state = getattr(context, "state", {}) if context is not None else {}
    if not isinstance(state, dict):
        return {}
    return _drop_empty(
        {
            "last_screen_result": _compact_screen_handoff(state.get("last_screen_result")),
            "last_recommendation_event_eval": _compact_recommendation_handoff(
                state.get("last_recommendation_event_eval")
            ),
            "last_ai_report": _compact_ai_report_handoff(state.get("last_ai_report")),
            "last_strategy_decision": _compact_strategy_handoff(state.get("last_strategy_decision")),
        }
    )


def _compact_screen_handoff(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    payload = _pick_fields(
        value,
        ("scan_scope", "summary", "data_quality", "decision_brief", "selection_brief", "next_action", "next_tool"),
    )
    payload["theme_context"] = _compact_theme_context(value.get("theme_context"))
    payload["action_plan"] = _pick_fields(
        value.get("action_plan"),
        (
            "candidate_action",
            "new_buy_allowed",
            "ai_review_allowed",
            "trade_readiness",
            "reason",
            "next_step",
            "data_quality_gate",
            "quality_gate",
            "review_targets",
        ),
    )
    payload["quality_gate"] = value.get("quality_gate") if isinstance(value.get("quality_gate"), dict) else {}
    payload["symbols_for_report"] = _candidate_rows(value.get("symbols_for_report"), 6)
    payload["report_candidates"] = _candidate_rows(value.get("report_candidates"), 6)
    payload["watch_candidates"] = _candidate_rows(value.get("watch_candidates"), 6)
    payload["top_candidates"] = _candidate_rows(value.get("top_candidates"), 6)
    payload["candidate_guard_summary"] = _compact_candidate_guard(value.get("candidate_guard_summary"))
    return _drop_empty(payload)


def _compact_theme_context(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return _drop_empty(
        {
            "event_mainlines": _clip_text(value.get("event_mainlines"), 240),
            "today_activity": _clip_text(value.get("today_activity"), 240),
            "theme_radar": _clip_text(value.get("theme_radar"), 240),
            "theme_radar_source": value.get("theme_radar_source"),
            "hot_concepts": _as_list(value.get("hot_concepts"))[:6],
        }
    )


def _compact_recommendation_handoff(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    selection = value.get("policy_selection") if isinstance(value.get("policy_selection"), dict) else {}
    return _drop_empty(
        {
            "result_summary": str(value.get("result_summary") or "")[:1000],
            "metadata": value.get("metadata") if isinstance(value.get("metadata"), dict) else {},
            "policy_selection": {
                **_pick_fields(
                    selection,
                    ("status", "selection_strategy", "top_k", "recommend_date", "uses_promoted_ranking", "action_plan"),
                ),
                "picks": _candidate_rows(selection.get("picks"), 6),
            },
            "candidate_guard_summary": _compact_candidate_guard(value.get("candidate_guard_summary")),
        }
    )


def _compact_ai_report_handoff(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    payload = _pick_fields(
        value, ("ok", "reason", "model", "stock_count", "reviewed_codes", "next_action", "next_tool")
    )
    payload["reviewed_symbols"] = _candidate_rows(value.get("reviewed_symbols"), 8)
    payload["candidate_guard_summary"] = _compact_candidate_guard(value.get("candidate_guard_summary"))
    return _drop_empty(payload)


def _compact_strategy_handoff(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    payload = _pick_fields(
        value,
        (
            "ok",
            "status",
            "reason",
            "report_source",
            "candidate_count",
            "reviewed_codes",
            "screen_summary",
            "decision_brief",
            "next_action",
            "message",
        ),
    )
    payload["reviewed_symbols"] = _candidate_rows(value.get("reviewed_symbols"), 8)
    payload["candidate_guard_summary"] = _compact_candidate_guard(value.get("candidate_guard_summary"))
    return _drop_empty(payload)


def _compact_candidate_guard(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    payload = _pick_fields(value, ("direct_buy_blocked_count", "message"))
    payload["candidates"] = _candidate_guard_rows(value.get("candidates"), 5)
    return _drop_empty(payload)


def _candidate_guard_rows(value: Any, limit: int) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [_compact_candidate_guard_row(row) for row in value[:limit] if isinstance(row, dict)]


def _compact_candidate_guard_row(row: dict[str, Any]) -> dict[str, Any]:
    return _pick_fields(
        row,
        (
            "code",
            "name",
            "reason",
            "action_status",
            "label_ready",
            "trade_readiness",
            "new_buy_allowed",
            "risk_factors",
            "next_step",
        ),
    )


def _candidate_rows(value: Any, limit: int) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    rows: list[tuple[int, dict[str, Any], dict[str, Any]]] = []
    for index, item in enumerate(value):
        row = _compact_candidate(item) if isinstance(item, dict) else _scalar_candidate(item)
        if row:
            rank_row = item if isinstance(item, dict) else row
            rows.append((index, row, rank_row))
    ranked_rows = sorted(rows, key=lambda item: _candidate_rank_key(item[2], item[0]), reverse=True)
    return [row for _index, row, _rank_row in ranked_rows[:limit]]


def _compact_candidate(row: dict[str, Any]) -> dict[str, Any]:
    fields = (
        "code",
        "name",
        "tag",
        "tier",
        "quality",
        "why",
        "evidence",
        "selection_source",
        "source_type",
        "track",
        "stage",
        "candidate_lane",
        "entry_type",
        "strategic_theme",
        "theme_score",
        "theme_source",
        "theme_event_id",
        "theme_event_date",
        "theme_event_title",
        "theme_event_reason",
        "priority_rank",
        "priority_score",
        "shadow_score",
        "score",
        "selection_strategy",
        "recommend_date",
        "is_ai_recommended",
        "selected_for_report",
        "funnel_score",
        "recommend_count",
        "candidate_shadow_score",
        "candidate_quality_score",
        "risk_adjusted_quality_score",
        "entry_risk_penalty",
        "rank_reason",
        "quality_factors",
        "risk_factors",
        "action_status",
        "status",
        "trade_readiness",
        "new_buy_allowed",
        "ai_review_allowed",
        "next_step",
        "candidate_shadow_grade",
        "entry_quality_score",
        "entry_quality_grade",
        "entry_quality_risk_flags",
        "label_ready",
        "label_status",
    )
    payload = _pick_fields(row, fields)
    if "code" not in payload and (code := _candidate_code(row)):
        payload["code"] = code
    for field in ("theme_event_title", "theme_event_reason"):
        if field in payload:
            payload[field] = _clip_text(payload[field], 240)
    return _drop_empty(payload)


def _scalar_candidate(value: Any) -> dict[str, Any]:
    text = str(value or "").strip()
    if not text:
        return {}
    return {"code": text} if any(char.isdigit() for char in text) else {"name": text}


def _candidate_code(row: dict[str, Any]) -> str:
    return str(
        row.get("symbol")
        or row.get("stock_code")
        or row.get("stockCode")
        or row.get("ticker")
        or row.get("sec_code")
        or ""
    ).strip()


def _pick_fields(value: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return _drop_empty({field: value.get(field) for field in fields})


def _clip_text(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    return text if len(text) <= limit else text[:limit] + "..."


def _drop_empty(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value not in (None, "", [], {})}


def _synthesis_prompt(run: WorkflowRun, results: list[dict[str, Any]]) -> str:
    script_prompt = ""
    if isinstance(run.script, dict):
        script_prompt = str(run.script.get("synthesis_prompt", "") or "").strip()
    handoff_summary = _synthesis_handoff_summary(results)
    agent_results = _synthesis_agent_results(results)
    return (
        "请基于以下动态 workflow 执行结果，给用户输出最终中文答复。\n"
        "要求：只使用 agent 结果里的事实；如果某步失败，明确说明影响和降级结论。\n"
        f"{_SYNTHESIS_REQUIREMENTS}\n"
        f"模型脚本的汇总要求:\n{script_prompt or '-'}\n\n"
        f"用户请求:\n{run.user_text}\n\n"
        f"workflow script:\n{json.dumps(run.script, ensure_ascii=False, default=str)[:4000]}\n\n"
        f"priority candidate handoff:\n{json.dumps(handoff_summary, ensure_ascii=False, default=str)[:6000]}\n\n"
        f"agent results:\n{json.dumps(agent_results, ensure_ascii=False, default=str)[:12000]}"
    )


def _synthesis_agent_results(results: list[dict[str, Any]]) -> list[Any]:
    return [_synthesis_agent_result(item) for item in results]


def _synthesis_agent_result(item: Any) -> Any:
    if not isinstance(item, dict):
        return item
    result = item.get("result")
    if not isinstance(result, dict) or "handoff_state" not in result:
        return item
    clean = dict(item)
    clean_result = dict(result)
    clean_result.pop("handoff_state", None)
    clean_result["handoff_state_ref"] = "see priority candidate handoff"
    clean["result"] = clean_result
    return clean


def _synthesis_handoff_summary(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summary: list[dict[str, Any]] = []
    aggregate_handoff: dict[str, Any] = {}
    seen_keys: set[str] = set()
    for item in reversed(results):
        result = item.get("result") if isinstance(item, dict) else {}
        handoff = result.get("handoff_state") if isinstance(result, dict) else {}
        if not isinstance(handoff, dict) or not handoff:
            continue
        handoff = _latest_handoff_keys(handoff, seen_keys)
        if not handoff:
            continue
        aggregate_handoff.update(handoff)
        step = item.get("step") if isinstance(item.get("step"), dict) else {}
        summary.append(
            _drop_empty(
                {
                    "step_id": step.get("step_id"),
                    "title": step.get("title"),
                    "handoff_state": handoff,
                }
            )
        )
    ordered = list(reversed(summary))
    if ordered and (conclusion := _candidate_conclusion_from_handoff(aggregate_handoff)):
        ordered[0] = {"candidate_conclusion": conclusion, **ordered[0]}
    return ordered


def _latest_handoff_keys(handoff: dict[str, Any], seen_keys: set[str]) -> dict[str, Any]:
    latest: dict[str, Any] = {}
    for key, value in handoff.items():
        if key in seen_keys or value in (None, "", [], {}):
            continue
        seen_keys.add(key)
        latest[key] = value
    return latest


def _collect_synthesis(
    provider: Any,
    prompt: str,
    system_prompt: str,
    *,
    fallback_text: str = "",
) -> tuple[str, dict[str, int]]:
    text_parts: list[str] = []
    usage = {"input_tokens": 0, "output_tokens": 0}
    for chunk in provider.chat_stream([{"role": "user", "content": prompt}], [], system_prompt):
        if chunk.get("type") == "text_delta":
            text_parts.append(str(chunk.get("text", "")))
        elif chunk.get("type") == "usage":
            usage["input_tokens"] += int(chunk.get("input_tokens", 0) or 0)
            usage["output_tokens"] += int(chunk.get("output_tokens", 0) or 0)
    text = "".join(text_parts).strip()
    return (text or fallback_text or _fallback_summary([]), usage)


def _fallback_summary(results: list[dict[str, Any]]) -> str:
    lines = ["动态 workflow 已完成，以下是各 sub-agent 的结果摘要："]
    if conclusion := _fallback_candidate_conclusion(results):
        lines.append(conclusion)
    for item in results:
        step = item.get("step", {})
        result = item.get("result", {})
        title = step.get("title", "任务")
        status = result.get("status", "unknown")
        content = result.get("result") or result.get("error") or "无结果"
        lines.append(f"- {title} [{status}]: {str(content)[:500]}")
        for line in _fallback_background_lines(result.get("background_tasks")):
            lines.append(f"  后台: {line}")
        for line in _fallback_handoff_lines(result.get("handoff_state")):
            lines.append(f"  证据: {line}")
    return "\n".join(lines)


def _fallback_background_lines(tasks: Any) -> list[str]:
    lines: list[str] = []
    for task in _as_list(tasks):
        if not isinstance(task, dict):
            continue
        name = str(task.get("tool_name") or task.get("task_id") or "background").strip()
        status = str(task.get("status") or "").strip()
        if summary := _clip_text(task.get("result_summary"), 500):
            lines.append(f"{name} [{status}]: {summary}")
        elif task.get("error"):
            lines.append(f"{name} [{status or 'failed'}]: {_clip_text(task.get('error'), 300)}")
    return lines


def _fallback_candidate_conclusion(results: list[dict[str, Any]]) -> str:
    for item in reversed(results):
        result = item.get("result") if isinstance(item, dict) else {}
        handoff = result.get("handoff_state") if isinstance(result, dict) else {}
        if not isinstance(handoff, dict):
            continue
        if conclusion := _candidate_conclusion_from_handoff(handoff):
            return str(conclusion.get("line") or "")
    return ""


def _candidate_conclusion_from_handoff(handoff: dict[str, Any]) -> dict[str, Any]:
    for stage in (
        "last_strategy_decision",
        "last_ai_report",
        "last_recommendation_event_eval",
        "last_screen_result",
    ):
        value = handoff.get(stage)
        if not isinstance(value, dict):
            continue
        if row := _fallback_stage_candidate(stage, value):
            merged = _fallback_merged_candidate(row, handoff)
            return _fallback_candidate_conclusion_payload(merged, value, handoff, stage)
    return {}


def _fallback_stage_candidate(stage: str, value: dict[str, Any]) -> dict[str, Any]:
    return _first_candidate_row(_fallback_stage_candidates(stage, value))


def _fallback_candidate_conclusion_payload(
    row: dict[str, Any], stage: dict[str, Any], handoff: dict[str, Any], source_stage: str
) -> dict[str, Any]:
    line = _fallback_candidate_line(row, stage, handoff)
    return _drop_empty(
        {
            "line": line,
            "code": str(row.get("code") or "").strip(),
            "name": str(row.get("name") or "").strip(),
            "action_status": str(row.get("action_status") or "").strip(),
            "evidence": _fallback_evidence_items(row),
            "quality_factors": _fallback_text_items(row.get("quality_factors"), 4, 120),
            "risk_factors": _fallback_risk_items(row, 4, 120),
            "guard_reason": _fallback_guard_reason_from_handoff(row, stage, handoff),
            "next_step": _fallback_next_value(row, stage),
            "source_stage": source_stage,
        }
    )


def _fallback_candidate_line(row: dict[str, Any], stage: dict[str, Any], handoff: dict[str, Any]) -> str:
    guard_reason = _fallback_guard_reason_from_handoff(row, stage, handoff)
    parts = [
        f"{_fallback_candidate_prefix(row, guard_reason)} {_fallback_candidate_name(row)}",
        _fallback_status_part(row),
        _fallback_evidence_part(row),
        _fallback_quality_part(row),
        _fallback_risk_part(row),
        _fallback_guard_part(guard_reason),
        _fallback_next_part(row, stage),
    ]
    return "候选结论: " + "；".join(part for part in parts if part)


def _fallback_candidate_prefix(row: dict[str, Any], guard_reason: str = "") -> str:
    status = str(row.get("action_status") or "").strip()
    if status == "ready_for_ai_review":
        return "受限复核候选" if guard_reason else "首选"
    if status == "watch_only":
        return "观察候选"
    if status.startswith("blocked_"):
        return "阻断候选"
    return "候选"


def _fallback_merged_candidate(row: dict[str, Any], handoff: dict[str, Any]) -> dict[str, Any]:
    code = str(row.get("code") or "").strip()
    merged: dict[str, Any] = {}
    for stage in ("last_screen_result", "last_recommendation_event_eval", "last_ai_report", "last_strategy_decision"):
        value = handoff.get(stage)
        if not isinstance(value, dict):
            continue
        for candidate in _fallback_stage_candidates(stage, value):
            if _candidate_matches(candidate, code):
                merged.update(_drop_empty(candidate))
    merged.update(_drop_empty(row))
    return merged


def _fallback_candidate_name(row: dict[str, Any]) -> str:
    code = str(row.get("code") or "").strip()
    name = str(row.get("name") or "").strip()
    return " ".join(part for part in (code, name) if part) or "候选"


def _fallback_status_part(row: dict[str, Any]) -> str:
    parts = []
    if status := str(row.get("action_status") or "").strip():
        parts.append(f"状态={status}")
    if readiness := str(row.get("trade_readiness") or "").strip():
        parts.append(f"交易就绪={readiness}")
    if row.get("new_buy_allowed") is False:
        parts.append("不允许新增买入")
    return "，".join(parts)


def _fallback_evidence_part(row: dict[str, Any]) -> str:
    evidence = _fallback_evidence_items(row)
    return f"证据={','.join(evidence)}" if evidence else ""


def _fallback_evidence_items(row: dict[str, Any]) -> list[str]:
    evidence = [
        _grade_score_part("候选影子", row.get("candidate_shadow_grade"), row.get("candidate_shadow_score")),
        _grade_score_part("入场", row.get("entry_quality_grade"), row.get("entry_quality_score")),
        _score_part("漏斗分", row.get("funnel_score")),
        _score_part("风险调整分", row.get("risk_adjusted_quality_score")),
        _score_part("候选质量分", row.get("candidate_quality_score")),
        _score_part("优先分", row.get("priority_score")),
        _theme_evidence_part(row),
    ]
    return [part for part in evidence if part]


def _fallback_quality_part(row: dict[str, Any]) -> str:
    factors = _fallback_text_items(row.get("quality_factors"), 3, 80)
    return f"亮点={','.join(factors)}" if factors else ""


def _fallback_risk_part(row: dict[str, Any]) -> str:
    risks = _fallback_risk_items(row, 3, 80)
    return f"风险={','.join(risks)}" if risks else ""


def _fallback_risk_items(row: dict[str, Any], limit: int, clip: int) -> list[str]:
    risks: list[str] = []
    for value in (row.get("risk_factors"), row.get("entry_quality_risk_flags")):
        for item in _fallback_text_items(value, limit, clip):
            if item not in risks:
                risks.append(item)
            if len(risks) >= limit:
                return risks
    return risks


def _fallback_text_items(value: Any, limit: int, clip: int) -> list[str]:
    return [_clip_text(item, clip) for item in _as_list(value)[:limit] if str(item or "").strip()]


def _theme_evidence_part(row: dict[str, Any]) -> str:
    theme = str(row.get("strategic_theme") or row.get("theme") or "").strip()
    if not theme:
        return ""
    source = str(row.get("theme_source") or "").strip()
    label = "事件主线" if source == "ths_hot_event" else "主题"
    reason = str(row.get("theme_event_reason") or "").strip()
    return f"{label}{theme}({reason})" if reason else f"{label}{theme}"


def _fallback_guard_part(reason: str) -> str:
    return f"护栏={reason}" if reason else ""


def _fallback_guard_reason_from_handoff(row: dict[str, Any], stage: dict[str, Any], handoff: dict[str, Any]) -> str:
    if reason := _fallback_guard_reason(row, stage):
        return reason
    for value in handoff.values():
        if isinstance(value, dict) and (reason := _fallback_guard_reason(row, value)):
            return reason
    return ""


def _fallback_guard_reason(row: dict[str, Any], stage: dict[str, Any]) -> str:
    guard = stage.get("candidate_guard_summary") if isinstance(stage.get("candidate_guard_summary"), dict) else {}
    candidates = _as_list(guard.get("candidates")) if isinstance(guard, dict) else []
    code = str(row.get("code") or "").strip()
    for item in candidates:
        if isinstance(item, dict) and str(item.get("code") or "").strip() == code and item.get("reason"):
            return str(item["reason"])
    first = next((item for item in candidates if isinstance(item, dict) and item.get("reason")), {})
    if first:
        return str(first["reason"])
    if reason := _fallback_gate_reason(row, stage):
        return reason
    if reason := candidate_guard_reason(row):
        return reason
    return ""


def _fallback_gate_reason(row: dict[str, Any], stage: dict[str, Any]) -> str:
    action_plan = stage.get("action_plan") if isinstance(stage.get("action_plan"), dict) else {}
    for gate in _fallback_gate_sources(stage, action_plan):
        if reason := _gate_reason_for_candidate(row, gate):
            return reason
    return ""


def _fallback_gate_sources(stage: dict[str, Any], action_plan: dict[str, Any]) -> list[dict[str, Any]]:
    keys = ("review_targets", "quality_gate", "data_quality_gate")
    gates = [action_plan.get(key) for key in keys]
    gates.extend(stage.get(key) for key in keys)
    return [gate for gate in gates if isinstance(gate, dict)]


def _gate_reason_for_candidate(row: dict[str, Any], gate: dict[str, Any]) -> str:
    code = str(row.get("code") or "").strip()
    for item in _as_list(gate.get("candidates")):
        if isinstance(item, dict) and str(item.get("code") or "").strip() == code and item.get("reason"):
            return str(item["reason"])
    return str(gate.get("reason") or "")


def _fallback_next_part(row: dict[str, Any], stage: dict[str, Any]) -> str:
    return f"下一步={value}" if (value := _fallback_next_value(row, stage)) else ""


def _fallback_next_value(row: dict[str, Any], stage: dict[str, Any]) -> str:
    action_plan = stage.get("action_plan") if isinstance(stage.get("action_plan"), dict) else {}
    next_step = row.get("next_step") or stage.get("next_action") or action_plan.get("next_step")
    return str(next_step or "")


def _first_candidate_row(rows: list[Any]) -> dict[str, Any]:
    candidates = [row for row in rows if isinstance(row, dict) and (row.get("code") or row.get("name"))]
    if not candidates:
        return {}
    return max(enumerate(candidates), key=lambda item: _candidate_rank_key(item[1], item[0]))[1]


def _candidate_rank_key(row: dict[str, Any], index: int) -> tuple[int, int, float, int]:
    return (
        _candidate_status_rank(row),
        1 if row.get("selected_for_report") is True or row.get("is_ai_recommended") is True else 0,
        _candidate_best_score(row),
        -index,
    )


def _candidate_status_rank(row: dict[str, Any]) -> int:
    status = str(row.get("action_status") or row.get("status") or "").strip()
    if status == "ready_for_ai_review":
        return 4
    if status in {"candidate", "review_ready"}:
        return 3
    if status == "watch_only":
        return 2
    if status.startswith("blocked_"):
        return 1
    return 2


def _candidate_best_score(row: dict[str, Any]) -> float:
    scores = (
        row.get("candidate_shadow_score"),
        row.get("risk_adjusted_quality_score"),
        row.get("candidate_quality_score"),
        row.get("entry_quality_score"),
        row.get("funnel_score"),
        row.get("priority_score"),
        row.get("shadow_score"),
        row.get("score"),
    )
    values = [_score_float(value) for value in scores]
    return max((value for value in values if value is not None), default=0.0)


def _score_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fallback_stage_candidates(stage: str, value: dict[str, Any]) -> list[dict[str, Any]]:
    if stage == "last_screen_result":
        selection = value.get("selection_brief") if isinstance(value.get("selection_brief"), dict) else {}
        rows: list[Any] = []
        rows.extend(_as_list(value.get("report_candidates")))
        rows.extend(_as_list(value.get("symbols_for_report")))
        rows.append(selection.get("primary_pick"))
        rows.extend(_as_list(selection.get("best_candidates")))
        rows.extend(_as_list(value.get("watch_candidates")))
        rows.extend(_as_list(value.get("top_candidates")))
    elif stage == "last_recommendation_event_eval":
        selection = value.get("policy_selection") if isinstance(value.get("policy_selection"), dict) else {}
        rows = _as_list(selection.get("picks"))
    else:
        rows = _as_list(value.get("reviewed_symbols"))
    return [row for row in rows if isinstance(row, dict)]


def _candidate_matches(row: dict[str, Any], code: str) -> bool:
    return bool(code and str(row.get("code") or "").strip() == code)


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _grade_score_part(label: str, grade: Any, score: Any) -> str:
    grade_text = str(grade or "").strip()
    score_text = _score_text(score)
    if grade_text and score_text:
        return f"{label}{grade_text}/{score_text}"
    return f"{label}{grade_text or score_text}" if grade_text or score_text else ""


def _score_part(label: str, score: Any) -> str:
    return f"{label}{value}" if (value := _score_text(score)) else ""


def _score_text(value: Any) -> str:
    try:
        return f"{float(value):.1f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return ""


def _fallback_handoff_lines(handoff: Any) -> list[str]:
    if not isinstance(handoff, dict):
        return []
    groups: list[list[str]] = []
    screen = handoff.get("last_screen_result")
    if isinstance(screen, dict):
        groups.append(tool_result_brief_lines("screen_stocks", screen, max_lines=3))
    recommendation = handoff.get("last_recommendation_event_eval")
    if isinstance(recommendation, dict):
        groups.append(tool_result_brief_lines("evaluate_recommendation_events", recommendation, max_lines=3))
    report = handoff.get("last_ai_report")
    if isinstance(report, dict):
        groups.append(tool_result_brief_lines("generate_ai_report", report, max_lines=3))
    decision = handoff.get("last_strategy_decision")
    if isinstance(decision, dict):
        groups.append(tool_result_brief_lines("generate_strategy_decision", decision, max_lines=3))
    return _balanced_handoff_lines(groups, limit=8)


def _balanced_handoff_lines(groups: list[list[str]], limit: int) -> list[str]:
    selected: list[str] = []
    seen: set[str] = set()
    for group in groups:
        _append_handoff_line(selected, seen, _first_handoff_line(group), limit)
    for group in groups:
        for line in group[1:]:
            _append_handoff_line(selected, seen, line, limit)
    return selected


def _first_handoff_line(lines: list[str]) -> str:
    return next((line for line in lines if line), "")


def _append_handoff_line(selected: list[str], seen: set[str], line: str, limit: int) -> None:
    if len(selected) >= limit or not line or line in seen:
        return
    seen.add(line)
    selected.append(line)
