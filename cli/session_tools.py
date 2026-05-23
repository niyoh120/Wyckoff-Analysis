"""Session export and fork helpers for local Wyckoff chat logs."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from cli.scratchpad import wyckoff_home


class SessionToolError(RuntimeError):
    """Raised when a session operation cannot be completed."""


@dataclass(frozen=True)
class SessionExportResult:
    path: Path
    session_id: str
    message_count: int


@dataclass(frozen=True)
class SessionForkResult:
    source_session_id: str
    new_session_id: str
    message_count: int


def _latest_session_id() -> str:
    from integrations.local_db import list_chat_sessions

    sessions = list_chat_sessions(limit=1)
    if not sessions:
        raise SessionToolError("暂无可操作的对话会话")
    return str(sessions[0]["session_id"])


def _default_export_path(session_id: str, output_format: str) -> Path:
    out_dir = wyckoff_home() / "sessions" / "exports"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    suffix = "json" if output_format == "json" else "md"
    return out_dir / f"wyckoff-session-{session_id[:8]}-{stamp}.{suffix}"


def _loads_json_maybe(text: str) -> Any:
    if not text:
        return ""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    data = dict(row)
    data["tool_calls"] = _loads_json_maybe(str(data.get("tool_calls", "") or ""))
    data["metadata"] = _loads_json_maybe(str(data.get("metadata", "") or ""))
    return data


def session_transcript_markdown(session_id: str, rows: list[dict[str, Any]]) -> str:
    lines = ["# Wyckoff Session Transcript", "", f"- session_id: `{session_id}`", f"- messages: `{len(rows)}`", ""]
    for row in rows:
        role = str(row.get("role", "") or "unknown")
        created_at = str(row.get("created_at", "") or "")
        lines.append(f"## {role} {created_at}".strip())
        model = str(row.get("model", "") or "")
        provider = str(row.get("provider", "") or "")
        if model or provider:
            lines.append(f"- model: `{provider or '-'}/{model or '-'}`")
        tokens_in = int(row.get("tokens_in") or 0)
        tokens_out = int(row.get("tokens_out") or 0)
        if tokens_in or tokens_out:
            lines.append(f"- tokens: `{tokens_in}/{tokens_out}`")
        tool_calls = row.get("tool_calls")
        if tool_calls:
            lines.append(f"- tool_calls: `{json.dumps(tool_calls, ensure_ascii=False)[:1000]}`")
        content = str(row.get("content", "") or "")
        if content:
            lines.extend(["", content])
        error = str(row.get("error", "") or "")
        if error:
            lines.extend(["", f"ERROR: {error}"])
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def export_session_transcript(
    *,
    session_id: str = "",
    output: Path | None = None,
    output_format: str = "md",
) -> SessionExportResult:
    """Export a lightweight transcript for a local chat session."""

    if output_format not in {"md", "json"}:
        raise SessionToolError("output_format 仅支持 md/json")

    from integrations.local_db import init_db, load_chat_logs

    init_db()
    resolved_session_id = session_id.strip() or _latest_session_id()
    rows = load_chat_logs(session_id=resolved_session_id, limit=1000)
    if not rows:
        raise SessionToolError(f"未找到会话: {resolved_session_id}")

    path = output or _default_export_path(resolved_session_id, output_format)
    path.parent.mkdir(parents=True, exist_ok=True)
    if output_format == "json":
        if path.suffix.lower() != ".json":
            path = path.with_suffix(".json")
        payload = {
            "schema": "wyckoff.session_export.v1",
            "session_id": resolved_session_id,
            "exported_at": datetime.now().isoformat(timespec="seconds"),
            "messages": [_normalize_row(row) for row in rows],
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    else:
        if path.suffix.lower() != ".md":
            path = path.with_suffix(".md")
        path.write_text(
            session_transcript_markdown(resolved_session_id, [_normalize_row(row) for row in rows]), encoding="utf-8"
        )

    return SessionExportResult(path=path, session_id=resolved_session_id, message_count=len(rows))


def _fork_metadata(raw_metadata: str, *, source_session_id: str) -> str:
    loaded = _loads_json_maybe(raw_metadata)
    if isinstance(loaded, dict):
        metadata = dict(loaded)
    elif loaded:
        metadata = {"original_metadata": loaded}
    else:
        metadata = {}
    metadata["_fork"] = {
        "source_session_id": source_session_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    return json.dumps(metadata, ensure_ascii=False, default=str)


def fork_session(
    *,
    session_id: str = "",
    new_session_id: str = "",
) -> SessionForkResult:
    """Duplicate a chat session into a new session id for branch-style follow-up."""

    from integrations.local_db import init_db, load_chat_logs, save_chat_log

    init_db()
    source_session_id = session_id.strip() or _latest_session_id()
    rows = load_chat_logs(session_id=source_session_id, limit=1000)
    if not rows:
        raise SessionToolError(f"未找到会话: {source_session_id}")

    target_session_id = new_session_id.strip() or uuid.uuid4().hex[:12]
    for row in rows:
        save_chat_log(
            target_session_id,
            str(row.get("role", "") or ""),
            str(row.get("content", "") or ""),
            model=str(row.get("model", "") or ""),
            provider=str(row.get("provider", "") or ""),
            tokens_in=int(row.get("tokens_in") or 0),
            tokens_out=int(row.get("tokens_out") or 0),
            elapsed_s=float(row.get("elapsed_s") or 0),
            error=str(row.get("error", "") or ""),
            tool_calls_json=str(row.get("tool_calls", "") or ""),
            metadata_json=_fork_metadata(str(row.get("metadata", "") or ""), source_session_id=source_session_id),
        )

    return SessionForkResult(
        source_session_id=source_session_id,
        new_session_id=target_session_id,
        message_count=len(rows),
    )
