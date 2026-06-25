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
    phase: str = ""
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
            "phase": self.phase,
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
            phase=str(payload.get("phase", "")),
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
        return self.context.label

    def plan_payload(self) -> dict[str, Any]:
        return {
            "workflow": self.workflow,
            "label": self.label,
            "allowed_tools": list(self.allowed_tools),
            "route": self.context.route_payload(),
            "script": self.script,
            "steps": [step.to_dict() for step in self.steps],
        }

    def refresh_current_step(self) -> None:
        for idx, step in enumerate(self.steps):
            if step.status not in TERMINAL_STATUSES:
                self.current_step = idx
                return
        self.current_step = len(self.steps)
