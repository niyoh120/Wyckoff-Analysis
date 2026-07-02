"""Workflow model objects shared by runtime, TUI, and local persistence."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

PENDING = "pending"
RUNNING = "running"
PAUSED = "paused"
COMPLETED = "completed"
FAILED = "failed"
SKIPPED = "skipped"
STOPPED = "stopped"

TERMINAL_STATUSES = {COMPLETED, FAILED, SKIPPED, STOPPED}


@dataclass(frozen=True)
class WorkflowContext:
    """A bounded runtime mode selected from the current user turn."""

    name: str
    label: str
    allowed_tools: tuple[str, ...] = ()
    system_hint: str = ""
    route_reason: str = ""
    route_confidence: float = 0.0
    route_matches: tuple[str, ...] = ()

    @property
    def is_general(self) -> bool:
        return self.name == "general_chat"

    def route_payload(self) -> dict[str, Any]:
        return {
            "reason": self.route_reason,
            "confidence": round(self.route_confidence, 2),
            "matches": list(self.route_matches),
        }


@dataclass
class WorkflowStep:
    """One planned or dynamically discovered workflow step."""

    step_id: str
    title: str
    tools: tuple[str, ...] = ()
    agent: str = ""
    prompt: str = ""
    context: str = ""
    rationale: str = ""
    success_criteria: str = ""
    risk_guard: str = ""
    phase: str = ""
    depends_on: tuple[str, ...] = ()
    tool_scope: tuple[str, ...] = ()
    status: str = PENDING
    summary: str = ""
    dynamic: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "title": self.title,
            "tools": list(self.tools),
            "agent": self.agent,
            "prompt": self.prompt,
            "context": self.context,
            "rationale": self.rationale,
            "success_criteria": self.success_criteria,
            "risk_guard": self.risk_guard,
            "phase": self.phase,
            "depends_on": list(self.depends_on),
            "tool_scope": list(self.tool_scope),
            "status": self.status,
            "summary": self.summary,
            "dynamic": self.dynamic,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> WorkflowStep:
        return cls(
            step_id=str(payload.get("step_id", "")),
            title=str(payload.get("title", "")),
            tools=tuple(payload.get("tools") or ()),
            agent=str(payload.get("agent", "")),
            prompt=str(payload.get("prompt", "")),
            context=str(payload.get("context", "")),
            rationale=str(payload.get("rationale", "")),
            success_criteria=str(payload.get("success_criteria", "")),
            risk_guard=str(payload.get("risk_guard", "")),
            phase=str(payload.get("phase", "")),
            depends_on=tuple(str(item) for item in payload.get("depends_on") or ()),
            tool_scope=tuple(str(item) for item in payload.get("tool_scope") or ()),
            status=str(payload.get("status") or PENDING),
            summary=str(payload.get("summary") or ""),
            dynamic=bool(payload.get("dynamic")),
        )


@dataclass
class WorkflowRun:
    """A persisted dynamic workflow run."""

    run_id: str
    session_id: str
    user_text: str
    context: WorkflowContext
    steps: list[WorkflowStep] = field(default_factory=list)
    script: dict[str, Any] = field(default_factory=dict)
    status: str = RUNNING
    current_step: int = 0
    result_summary: str = ""

    @property
    def allowed_tools(self) -> tuple[str, ...]:
        return self.context.allowed_tools

    @property
    def workflow(self) -> str:
        return self.context.name

    @property
    def label(self) -> str:
        title = " ".join(str(self.script.get("title") or "").split())
        return title[:80] if title else self.context.label

    def plan_payload(self) -> dict[str, Any]:
        return {
            "workflow": self.workflow,
            "label": self.label,
            "allowed_tools": list(self.allowed_tools),
            "route": self.context.route_payload(),
            "script": self.script,
            "steps": [self.step_payload(step) for step in self.steps],
        }

    def step_payload(self, step: WorkflowStep) -> dict[str, Any]:
        payload = step.to_dict()
        if effective_scope := _effective_tool_scope(step.tool_scope, self.allowed_tools):
            payload["effective_tool_scope"] = list(effective_scope)
        return payload

    def refresh_current_step(self) -> None:
        for idx, step in enumerate(self.steps):
            if step.status not in TERMINAL_STATUSES:
                self.current_step = idx
                return
        self.current_step = len(self.steps)


def _effective_tool_scope(tool_scope: tuple[str, ...], allowed_tools: tuple[str, ...]) -> tuple[str, ...]:
    allowed = tuple(name for name in allowed_tools if name and not name.startswith("delegate_to_"))
    if tool_scope:
        return tuple(name for name in tool_scope if name and not name.startswith("delegate_to_") and name in allowed)
    return allowed
