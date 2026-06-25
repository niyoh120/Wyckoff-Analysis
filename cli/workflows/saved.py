"""Saved dynamic workflow scripts."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from cli.scratchpad import wyckoff_home

_NAME_RE = re.compile(r"[^a-zA-Z0-9_-]+")
_BUILTIN_WORKFLOWS: dict[str, dict[str, Any]] = {
    "deep-research": {
        "name": "deep-research",
        "source_run_id": "builtin",
        "workflow": "dynamic_task",
        "label": "深度研究",
        "allowed_tools": [
            "search_stock_by_name",
            "analyze_stock",
            "get_market_overview",
            "get_market_history",
            "query_history",
            "screen_stocks",
            "delegate_to_research",
            "delegate_to_analysis",
        ],
        "route": {"reason": "内置 deep-research workflow", "confidence": 1.0, "matches": ["deep-research"]},
        "saved_at": "builtin",
        "script": {
            "title": "深度研究",
            "rationale": "并发收集市场和结构证据，再形成投资研究结论。",
            "phases": [
                {
                    "id": "research",
                    "title": "并发取证",
                    "tasks": [
                        {
                            "id": "market_evidence",
                            "title": "市场和数据证据",
                            "agent": "research",
                            "prompt": "围绕用户输入做深度研究的数据取证：{args}",
                            "context": "优先使用可用工具获取市场水温、历史走势、候选或相关标的。",
                        },
                        {
                            "id": "structure_evidence",
                            "title": "结构和风险证据",
                            "agent": "analysis",
                            "prompt": "围绕用户输入做结构、风险和反证分析：{args}",
                            "context": "关注 Wyckoff 结构、量价关系、关键触发位和失效位。",
                        },
                    ],
                },
                {
                    "id": "synthesis",
                    "title": "研究结论",
                    "tasks": [
                        {
                            "id": "research_synthesis",
                            "title": "合成研究结论",
                            "agent": "analysis",
                            "prompt": "整合前序证据，输出结构化研究结论和下一步验证清单。",
                        }
                    ],
                },
            ],
            "synthesis_prompt": "输出中文深度研究报告：结论、证据、反证、风险、下一步跟踪项。",
        },
    }
}


def save_workflow_script(name: str, run: dict[str, Any]) -> Path:
    """Persist a workflow run script as a reusable local command."""

    script = run.get("plan", {}).get("script", {})
    if not isinstance(script, dict) or not script:
        raise ValueError("workflow run has no saved script")
    payload = {
        "name": _safe_name(name),
        "source_run_id": run.get("run_id", ""),
        "workflow": run.get("workflow", ""),
        "label": run.get("label", ""),
        "allowed_tools": run.get("plan", {}).get("allowed_tools", []),
        "route": run.get("plan", {}).get("route", {}),
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "script": script,
    }
    directory = workflows_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{payload['name']}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return path


def load_saved_workflow(name: str) -> dict[str, Any] | None:
    safe_name = _safe_name(name)
    path = workflows_dir() / f"{safe_name}.json"
    if not path.is_file():
        return _BUILTIN_WORKFLOWS.get(safe_name)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def list_saved_workflows() -> list[dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = dict(_BUILTIN_WORKFLOWS)
    directory = workflows_dir()
    if directory.is_dir():
        for path in sorted(directory.glob("*.json")):
            payload = load_saved_workflow(path.stem)
            if payload and payload.get("name"):
                rows[str(payload["name"])] = payload
    return [rows[name] for name in sorted(rows)]


def workflows_dir() -> Path:
    return wyckoff_home() / "workflows"


def _safe_name(name: str) -> str:
    cleaned = _NAME_RE.sub("-", name.strip()).strip("-_").lower()
    if not cleaned:
        raise ValueError("workflow name is empty")
    return cleaned[:64]
