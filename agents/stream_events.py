"""Helpers for building agent progress stream events."""

from __future__ import annotations

from typing import Any


def stream_event(event_type: str, **fields: Any) -> dict[str, Any]:
    """Build a progress event while dropping unset fields.

    Existing clients depend on top-level fields such as type, step,
    tool, success and duration. Newer events can add fields like
    stage or meta without changing the callback/SSE contract.
    """
    event: dict[str, Any] = {"type": event_type}
    event.update({key: value for key, value in fields.items() if value is not None})
    return event
