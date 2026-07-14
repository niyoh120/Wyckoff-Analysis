"""Regression test for the analyze_stock concurrent handoff race condition.

analyze_stock is registered as a concurrency-safe tool (cli/tools.py TOOL_SPECS),
so cli/runtime.py may run several analyze_stock calls for different stock codes
in a ThreadPoolExecutor. Each call ends with remember_stock_diagnosis() doing a
read-modify-write on tool_context.state["last_stock_diagnosis"]: read the
previous handoff, merge in the new row, write the merged result back. Without
a lock around that critical section, two concurrent writers can both read the
same stale snapshot and then each write back a merge computed from it, so
whichever one writes last silently erases the other's row (a lost update).

This test proves mutual exclusion directly: it instruments the read step to
detect whether more than one thread is ever inside the read-modify-write
critical section at the same time. With the real state_lock, that overlap
count must always be zero. Removing the lock (control experiment) must
reliably produce an overlap, proving both that real concurrent execution is
happening and that the harness would catch the bug.
"""

from __future__ import annotations

import threading
import time

from agents import diagnosis_tools
from agents.tool_context import ToolContext

WORKER_COUNT = 8
CRITICAL_SECTION_DELAY_SECONDS = 0.05


class _NullLock:
    """Minimal no-op lock usable as a drop-in for threading.Lock via `with`."""

    def __enter__(self) -> None:
        return None

    def __exit__(self, *exc_info: object) -> None:
        return None


class _OverlapDetectingState(dict):
    """dict subclass that counts how many threads are simultaneously inside
    remember_stock_diagnosis's read-modify-write critical section.

    Plain `dict` methods can't be monkeypatched (C-level, read-only slots),
    so this subclass intercepts the "read previous handoff" call (the start
    of the critical section) to track concurrent entries, and sleeps to
    widen the window so any real overlap has time to manifest.
    """

    def __init__(self, *args, watched_key: str, **kwargs):
        super().__init__(*args, **kwargs)
        self._watched_key = watched_key
        self._active = 0
        self._lock = threading.Lock()
        self.max_observed_overlap = 0

    def get(self, key, default=None):  # noqa: A003 - intentional dict.get override
        value = super().get(key, default)
        if key == self._watched_key:
            with self._lock:
                self._active += 1
                self.max_observed_overlap = max(self.max_observed_overlap, self._active)
            time.sleep(CRITICAL_SECTION_DELAY_SECONDS)
            with self._lock:
                self._active -= 1
        return value


def _diagnosis_result(code: str) -> dict:
    return {
        "code": code,
        "name": f"stock-{code}",
        "health": "🟢健康",
        "accum_stage": "",
        "diagnosis_brief": {
            "status": "priority_watch",
            "label": "重点观察",
            "direct_buy_allowed": False,
            "next_step": "加入重点观察",
        },
        "candidate_score": 80.0,
    }


def _run_concurrent_diagnoses(context: ToolContext) -> None:
    codes = [f"{i:06d}" for i in range(WORKER_COUNT)]
    threads = [
        threading.Thread(target=diagnosis_tools.remember_stock_diagnosis, args=(context, _diagnosis_result(code)))
        for code in codes
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
        assert not thread.is_alive(), "remember_stock_diagnosis did not complete in time"


def test_remember_stock_diagnosis_is_race_free_under_concurrent_writers() -> None:
    """With the real state_lock in place, no two writers are ever inside the
    read-modify-write critical section at the same time, so all 6 most
    recent rows survive (the cap enforced by remember_stock_diagnosis).
    """
    context = ToolContext()
    state = _OverlapDetectingState(watched_key="last_stock_diagnosis")
    context.state = state

    _run_concurrent_diagnoses(context)

    assert state.max_observed_overlap == 1, "the lock should serialize every writer"
    recorded_codes = {row["code"] for row in context.state["last_stock_diagnosis"]["diagnosed_symbols"]}
    assert len(recorded_codes) == 6


def test_concurrent_writers_overlap_when_lock_is_removed() -> None:
    """Control experiment proving the harness above is load-bearing.

    Swap tool_context.state_lock for a no-op context manager (simulating the
    pre-fix code that had no locking) and confirm the exact same harness now
    reliably detects multiple writers inside the critical section at once --
    the precondition for the lost-update bug fixed by adding state_lock.
    """
    context = ToolContext()
    state = _OverlapDetectingState(watched_key="last_stock_diagnosis")
    context.state = state
    context.state_lock = _NullLock()  # simulate the pre-fix, unlocked code path

    _run_concurrent_diagnoses(context)

    assert state.max_observed_overlap > 1, "expected concurrent writers to overlap without the lock"


def test_lock_serializes_writers_instead_of_deadlocking() -> None:
    """Sanity check: threading.Lock is not reentrant, so remember_stock_diagnosis
    must not try to acquire it twice on the same thread (that would deadlock
    instead of losing data, which is a worse failure mode).
    """
    context = ToolContext()

    _run_concurrent_diagnoses(context)

    recorded_codes = {row["code"] for row in context.state["last_stock_diagnosis"]["diagnosed_symbols"]}
    assert len(recorded_codes) == 6
