"""Shared background task progress reporter."""

from __future__ import annotations

from collections.abc import Callable
from contextvars import ContextVar

ProgressReporter = Callable[[str, str, float], None]
_reporter: ContextVar[ProgressReporter | None] = ContextVar("_reporter", default=None)


def set_reporter(cb: ProgressReporter | None) -> None:
    _reporter.set(cb)


def report_progress(stage: str, detail: str = "", progress: float = -1.0) -> None:
    cb = _reporter.get()
    if cb is not None:
        cb(stage, detail, progress)
