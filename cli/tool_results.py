"""Tool result context budgeting helpers."""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from cli.scratchpad import wyckoff_home

INLINE_TOOL_RESULT_MAX_CHARS = 8_000
PREVIEW_CHARS = 2_000

_SAFE_RE = re.compile(r"[^a-zA-Z0-9_.-]+")


def serialize_tool_result(result: Any) -> str:
    """Serialize a tool result exactly once for message context."""

    return json.dumps(_json_safe(result), ensure_ascii=False, default=str, allow_nan=False)


def _json_safe(value: Any) -> Any:
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    if hasattr(value, "item"):
        try:
            return _json_safe(value.item())
        except Exception:
            return str(value)
    return value


def _safe_part(value: str) -> str:
    cleaned = _SAFE_RE.sub("_", value or "unknown").strip("_")
    return cleaned[:80] or "unknown"


def _tool_node_id(tool_name: str, tool_call_id: str, content: str) -> str:
    digest = hashlib.sha1(content.encode("utf-8", errors="ignore")).hexdigest()[:10]
    return f"T_{_safe_part(tool_name)[:24]}_{_safe_part(tool_call_id)[:24]}_{digest}"


def _append_tool_result_index(
    *,
    node_id: str,
    tool_name: str,
    tool_call_id: str,
    path: Path,
    content: str,
) -> None:
    index_path = path.parent / "index.jsonl"
    entry = {
        "node_id": node_id,
        "tool_name": tool_name,
        "tool_call_id": tool_call_id,
        "result_ref": str(path),
        "size_bytes": len(content.encode("utf-8")),
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    with index_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False))
        fh.write("\n")


def persist_large_tool_result(
    tool_name: str,
    tool_call_id: str,
    content: str,
    *,
    node_id: str = "",
) -> Path:
    """Persist a large tool result and return the file path."""

    results_dir = wyckoff_home() / "tool-results"
    results_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha1(content.encode("utf-8", errors="ignore")).hexdigest()[:10]
    stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    filename = f"{stamp}_{_safe_part(tool_name)}_{_safe_part(tool_call_id)}_{digest}.json"
    path = results_dir / filename
    path.write_text(content, encoding="utf-8")
    if node_id:
        _append_tool_result_index(
            node_id=node_id,
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            path=path,
            content=content,
        )
    return path


def _offloaded_tool_result_message(tool_name: str, node_id: str, path: Path, size_kb: int, preview: str) -> str:
    return (
        "[工具结果已卸载为可追溯节点]\n"
        f"node_id: {node_id}\n"
        f"tool: {tool_name}\n"
        f"result_ref: {path}\n"
        f"size: {size_kb} KB\n\n"
        "```mermaid\n"
        "graph LR\n"
        f'    {node_id}["{tool_name} result"] --> REF["result_ref"]\n'
        "```\n\n"
        f"预览:\n{preview}\n\n如需完整内容，请调用 read_file 读取 result_ref。"
    )


def _tool_result_preview(tool_name: str, result: Any, content: str) -> str:
    if tool_name == "screen_stocks" and isinstance(result, dict):
        preview = _screen_stocks_preview(result)
        if preview:
            return preview[:PREVIEW_CHARS]
    return content[:PREVIEW_CHARS]


def _screen_stocks_preview(result: dict[str, Any]) -> str:
    payload = _drop_empty_preview_fields(
        {
            "ok": result.get("ok"),
            "board": result.get("board"),
            "summary": result.get("summary"),
            "trade_mode": result.get("trade_mode"),
            "decision_brief": result.get("decision_brief"),
            "action_plan": result.get("action_plan"),
            "top_candidates": _preview_list(result.get("top_candidates"), 10),
            "symbols_for_report": _preview_list(result.get("symbols_for_report"), 12),
            "top_sectors": _preview_list(result.get("top_sectors"), 6),
            "omitted": "完整 trigger_groups 已写入 result_ref" if result.get("trigger_groups") else "",
        }
    )
    return serialize_tool_result(payload) if payload else ""


def _preview_list(value: Any, limit: int) -> list[Any]:
    return list(value[:limit]) if isinstance(value, list) else []


def _drop_empty_preview_fields(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if value is not None and value != "" and value != [] and value != {}
    }


def format_tool_result_for_context(
    tool_name: str,
    tool_call_id: str,
    result: Any,
    *,
    max_chars: int = INLINE_TOOL_RESULT_MAX_CHARS,
) -> str:
    """Return a context-safe tool message body.

    Results above the inline budget are written to disk and replaced with a
    stable preview plus a path the agent can read back if needed.
    """

    content = serialize_tool_result(result)
    if len(content) <= max_chars:
        return content

    node_id = _tool_node_id(tool_name, tool_call_id, content)
    path = persist_large_tool_result(tool_name, tool_call_id, content, node_id=node_id)
    size_kb = max(1, round(len(content.encode("utf-8")) / 1024))
    preview = _tool_result_preview(tool_name, result, content)
    return _offloaded_tool_result_message(tool_name, node_id, path, size_kb, preview)
