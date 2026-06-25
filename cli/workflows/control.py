"""Runtime controls for background workflow runs."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field


@dataclass
class WorkflowControl:
    run_id: str
    _stop: threading.Event = field(default_factory=threading.Event)
    _resume: threading.Event = field(default_factory=threading.Event)

    def __post_init__(self) -> None:
        self._resume.set()

    def pause(self) -> None:
        self._resume.clear()

    def resume(self) -> None:
        self._resume.set()

    def stop(self) -> None:
        self._stop.set()
        self._resume.set()

    def stopped(self) -> bool:
        return self._stop.is_set()

    def paused(self) -> bool:
        return not self._resume.is_set()

    def wait_if_paused(self, poll_s: float = 0.2) -> bool:
        while self.paused() and not self.stopped():
            time.sleep(poll_s)
        return not self.stopped()


_CONTROLS: dict[str, WorkflowControl] = {}
_LOCK = threading.Lock()


def register_workflow_control(run_id: str) -> WorkflowControl:
    control = WorkflowControl(run_id)
    with _LOCK:
        _CONTROLS[run_id] = control
    return control


def get_workflow_control(run_id: str) -> WorkflowControl | None:
    with _LOCK:
        return _CONTROLS.get(run_id)


def unregister_workflow_control(run_id: str) -> None:
    with _LOCK:
        _CONTROLS.pop(run_id, None)


def active_workflow_ids() -> list[str]:
    with _LOCK:
        return sorted(_CONTROLS)
