"""Build model context when resuming local chat sessions."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from cli.compaction import build_local_context_summary, estimate_tokens, find_tail_start_by_token_budget

RESUME_CONTEXT_TOKEN_BUDGET = 28_000
RESUME_TAIL_TOKEN_BUDGET = 18_000
RESUME_MAX_MESSAGES = 120

_ALLOWED_ROLES = {"user", "assistant", "tool"}
_KEEP_KEYS = {
    "role",
    "content",
    "tool_calls",
    "tool_call_id",
    "name",
    "reasoning_content",
}


@dataclass(frozen=True)
class ResumedContext:
    messages: list[dict[str, Any]]
    mode: str
    source_rows: int
    model_messages: int
    estimated_tokens: int


def build_resumed_model_context(rows: list[dict[str, Any]]) -> ResumedContext:
    """Return bounded model messages for a resumed chat session."""

    snapshot = _latest_message_snapshot(rows)
    messages = snapshot or _messages_from_chat_rows(rows)
    bounded, mode = _bound_resume_messages(messages)
    return ResumedContext(
        messages=bounded,
        mode=mode if snapshot else f"fallback_{mode}",
        source_rows=len(rows),
        model_messages=len(bounded),
        estimated_tokens=estimate_tokens(bounded),
    )


def _latest_message_snapshot(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for row in reversed(rows):
        metadata = _loads_json(str(row.get("metadata", "") or ""))
        if not isinstance(metadata, dict):
            continue
        messages = metadata.get("messages")
        if not isinstance(messages, list):
            continue
        cleaned = [_clean_message(item) for item in messages if isinstance(item, dict)]
        cleaned = [item for item in cleaned if item]
        if cleaned:
            return cleaned
    return []


def _messages_from_chat_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for row in rows:
        role = str(row.get("role", "") or "")
        if role not in {"user", "assistant"}:
            continue
        content = str(row.get("content", "") or "")
        if content:
            messages.append({"role": role, "content": content})
    return messages


def _clean_message(message: dict[str, Any]) -> dict[str, Any]:
    role = str(message.get("role", "") or "")
    if role not in _ALLOWED_ROLES:
        return {}
    cleaned = {key: message[key] for key in _KEEP_KEYS if key in message and message[key] not in (None, "")}
    cleaned["role"] = role
    content = cleaned.get("content")
    if content is not None and not isinstance(content, str):
        cleaned["content"] = json.dumps(content, ensure_ascii=False, default=str)
    if role != "assistant":
        cleaned.pop("reasoning_content", None)
    return cleaned


def _bound_resume_messages(messages: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str]:
    if not messages:
        return [], "empty"
    if len(messages) <= RESUME_MAX_MESSAGES and estimate_tokens(messages) <= RESUME_CONTEXT_TOKEN_BUDGET:
        return messages, "full"

    tail_start = find_tail_start_by_token_budget(messages, RESUME_TAIL_TOKEN_BUDGET)
    tail = messages[tail_start:]
    head = messages[:tail_start]
    summary = build_local_context_summary(head)
    bounded = [
        {
            "role": "user",
            "content": (
                "[SYSTEM CONTEXT - RESUMED SESSION]\n"
                "本会话是从历史记录恢复的。以下是较早历史的压缩摘要，只用于承接上下文；"
                "不要把它当作用户的新请求。\n\n"
                f"{summary}"
            ),
        },
        {"role": "assistant", "content": "已加载历史摘要，我会承接前文继续。"},
        *tail,
    ]
    return bounded, "summary_tail"


def _loads_json(raw: str) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None
