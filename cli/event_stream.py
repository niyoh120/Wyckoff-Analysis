"""Normalize local scratchpad traces into a stable agent event stream."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

EVENT_SCHEMA = "wyckoff.agent_event.v1"


def _event_type(entry_type: str) -> str:
    return {
        "init": "user_message",
        "thinking": "assistant_thinking",
        "tool_result": "tool_result",
        "compaction": "context_compaction",
        "final": "assistant_message",
        "error": "error",
    }.get(entry_type, entry_type or "unknown")


def _timestamp(value: Any) -> str:
    text = str(value or "")
    return text or datetime.now().isoformat(timespec="milliseconds")


def normalize_scratchpad_entry(entry: dict[str, Any], *, source: str = "") -> dict[str, Any]:
    """Convert one AgentScratchpad JSONL record to the public event schema."""

    entry_type = str(entry.get("type", "") or "")
    event: dict[str, Any] = {
        "schema": EVENT_SCHEMA,
        "type": _event_type(entry_type),
        "timestamp": _timestamp(entry.get("timestamp")),
    }
    if source:
        event["source"] = source
    session_id = str(entry.get("session_id", "") or "")
    if session_id:
        event["session_id"] = session_id

    if entry_type == "init":
        event["role"] = "user"
        event["content"] = entry.get("content", "")
    elif entry_type == "thinking":
        event["role"] = "assistant"
        event["content"] = entry.get("content", "")
    elif entry_type == "tool_result":
        event["tool_name"] = entry.get("toolName", "")
        event["args"] = entry.get("args", {})
        event["result"] = entry.get("result")
        event["status"] = entry.get("status", "ok")
        if "durationMs" in entry:
            event["duration_ms"] = entry.get("durationMs")
    elif entry_type == "compaction":
        event["before_messages"] = entry.get("beforeMessages", 0)
        event["after_messages"] = entry.get("afterMessages", 0)
    elif entry_type == "final":
        event["role"] = "assistant"
        event["content"] = entry.get("content", "")
        event["usage"] = entry.get("usage", {})
    elif entry_type == "error":
        event["error"] = entry.get("error", "")
        event["elapsed_s"] = entry.get("elapsed_s", 0)
    else:
        event["raw"] = entry
    return event


def load_scratchpad_events(path: Path) -> list[dict[str, Any]]:
    """Read an AgentScratchpad JSONL file as normalized events."""

    events: list[dict[str, Any]] = []
    source = path.name
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(entry, dict):
            events.append(normalize_scratchpad_entry(entry, source=source))
    return events


def scratchpad_events_jsonl(paths: list[Path]) -> str:
    lines: list[str] = []
    for path in paths:
        for event in load_scratchpad_events(path):
            lines.append(json.dumps(event, ensure_ascii=False, default=str))
    return "\n".join(lines) + ("\n" if lines else "")
