"""Recoverable context archive for compacted CLI messages."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from cli.scratchpad import _scrub, wyckoff_home

_CODE_RE = re.compile(r"\b\d{6}\b")
_FILE_RE = re.compile(r"(?:[\w.-]+/)+[\w.-]+")
_WORD_RE = re.compile(r"[\w\u4e00-\u9fff]{2,}")
_MAX_SUMMARY = 500
_MAX_INLINE = 400


def archive_root(archive_dir: str | Path | None = None) -> Path:
    root = Path(archive_dir).expanduser() if archive_dir else wyckoff_home() / "context_archive"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _safe_session_id(session_id: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(session_id or "default")).strip("_")
    return clean or "default"


def _message_text(message: dict[str, Any]) -> str:
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False, default=str)


def extract_archive_terms(messages: list[dict[str, Any]], summary: str = "") -> dict[str, list[str]]:
    text = "\n".join([summary, *(_message_text(m) for m in messages)])
    codes = list(dict.fromkeys(_CODE_RE.findall(text)))[:24]
    files = list(dict.fromkeys(_FILE_RE.findall(text)))[:24]
    words = [w for w in _WORD_RE.findall(text.lower()) if not w.isdigit()]
    keywords = list(dict.fromkeys(words))[:60]
    return {"codes": codes, "files": files, "keywords": keywords}


def _archive_id(session_id: str, messages: list[dict[str, Any]]) -> str:
    seed = json.dumps(messages, ensure_ascii=False, sort_keys=True, default=str)
    digest = hashlib.sha1(seed.encode("utf-8", errors="ignore")).hexdigest()[:12]
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    return f"ctx_{stamp}_{digest}"


def create_context_archive(
    messages: list[dict[str, Any]],
    summary: str,
    *,
    session_id: str = "",
    archive_dir: str | Path | None = None,
    tail_start: int | None = None,
    anchors: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    safe_session = _safe_session_id(session_id)
    root = archive_root(archive_dir) / safe_session
    root.mkdir(parents=True, exist_ok=True)
    compaction_id = _archive_id(safe_session, messages)
    messages_path = root / f"{compaction_id}.jsonl"
    meta_path = root / f"{compaction_id}.json"
    for idx, message in enumerate(messages):
        record = {"index": idx, "message": _scrub(message)}
        with messages_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    terms = extract_archive_terms(messages, summary)
    meta = {
        "compaction_id": compaction_id,
        "session_id": safe_session,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "message_count": len(messages),
        "message_range": [0, max(len(messages) - 1, 0)],
        "tail_start": tail_start,
        "summary": summary[:_MAX_SUMMARY],
        "anchors": anchors or [],
        "codes": terms["codes"],
        "files": terms["files"],
        "keywords": terms["keywords"],
        "archive_ref": f"archive://{safe_session}/{compaction_id}",
        "messages_path": str(messages_path),
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return meta


def _load_meta(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _meta_score(meta: dict[str, Any], query_terms: set[str]) -> int:
    searchable = " ".join(
        str(x)
        for x in [
            meta.get("compaction_id", ""),
            meta.get("summary", ""),
            *(meta.get("codes") or []),
            *(meta.get("files") or []),
            *(meta.get("keywords") or []),
        ]
    ).lower()
    return sum(1 for term in query_terms if term and term.lower() in searchable)


def search_context_archives(
    query: str,
    *,
    session_id: str = "",
    limit: int = 3,
    archive_dir: str | Path | None = None,
) -> list[dict[str, Any]]:
    root = archive_root(archive_dir)
    paths = list((root / _safe_session_id(session_id)).glob("*.json")) if session_id else list(root.glob("*/*.json"))
    terms = set(_CODE_RE.findall(query)) | {w.lower() for w in _WORD_RE.findall(query)}
    scored = [(score, meta) for path in paths if (meta := _load_meta(path)) and (score := _meta_score(meta, terms)) > 0]
    scored.sort(key=lambda item: (item[0], item[1].get("created_at", "")), reverse=True)
    return [meta for _score, meta in scored[: max(1, limit)]]


def restore_context_archive(ref: str, *, archive_dir: str | Path | None = None) -> list[dict[str, Any]]:
    match = re.search(r"archive://([^/]+)/([^/#\s]+)", str(ref or ""))
    if not match:
        return []
    session_id, compaction_id = match.groups()
    path = archive_root(archive_dir) / _safe_session_id(session_id) / f"{compaction_id}.jsonl"
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        with_value = json.loads(line)
        if isinstance(with_value, dict):
            rows.append(with_value)
    return rows


def archive_recall_lines(
    query: str,
    *,
    session_id: str = "",
    max_items: int = 2,
    archive_dir: str | Path | None = None,
) -> list[str]:
    metas = search_context_archives(query, session_id=session_id, limit=max_items, archive_dir=archive_dir)
    lines: list[str] = []
    for meta in metas:
        ref = meta.get("archive_ref", "")
        summary = str(meta.get("summary", ""))[:_MAX_INLINE]
        tags = ", ".join((meta.get("codes") or meta.get("files") or [])[:5])
        suffix = f" [{tags}]" if tags else ""
        lines.append(f"- {ref}{suffix}：{summary}")
    return lines
