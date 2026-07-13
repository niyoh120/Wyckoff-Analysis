from __future__ import annotations

from uuid import uuid4

from integrations import local_db

HYPOTHESIS_STATUSES = {"exploring", "testing", "validated", "monitoring", "rejected"}
EVIDENCE_TYPES = {"backtest", "stability", "attribution", "shadow", "report", "observation"}
EVIDENCE_VERDICTS = {"pass", "review", "fail"}
ALLOWED_TRANSITIONS = {
    "exploring": {"testing", "rejected"},
    "testing": {"validated", "rejected"},
    "validated": {"monitoring", "rejected"},
    "monitoring": {"validated", "rejected"},
    "rejected": {"exploring"},
}


def research_hypothesis(
    action: str,
    hypothesis_id: str = "",
    title: str = "",
    thesis: str = "",
    status: str = "",
    universe: str = "",
    signal_definition: str = "",
    invalidation_criteria: str = "",
    evidence_type: str = "",
    artifact_ref: str = "",
    verdict: str = "review",
    summary: str = "",
    metrics: dict | None = None,
    target_status: str = "",
    reason: str = "",
    limit: int = 50,
) -> dict:
    """Track a research hypothesis and the evidence used to promote or reject it."""
    try:
        normalized = str(action or "").strip().lower()
        if normalized == "create":
            return _create(title, thesis, universe, signal_definition, invalidation_criteria)
        if normalized == "list":
            return _list(status, limit)
        if normalized == "detail":
            return _detail(hypothesis_id)
        if normalized == "update":
            return _update(hypothesis_id, title, thesis, status, universe, signal_definition, invalidation_criteria)
        if normalized == "link_evidence":
            return _link_evidence(hypothesis_id, evidence_type, artifact_ref, verdict, summary, metrics or {})
        if normalized == "evaluate":
            return _evaluate(hypothesis_id)
        if normalized == "transition":
            return _transition(hypothesis_id, target_status, reason)
        return {"error": f"未知 action: {action}"}
    except (KeyError, ValueError) as exc:
        return {"error": str(exc)}


def _create(
    title: str,
    thesis: str,
    universe: str,
    signal_definition: str,
    invalidation_criteria: str,
) -> dict:
    clean_title = title.strip()
    clean_thesis = thesis.strip()
    if not clean_title or not clean_thesis:
        raise ValueError("create 需要 title 和 thesis")
    hypothesis = local_db.create_research_hypothesis(
        {
            "hypothesis_id": f"hyp_{uuid4().hex[:12]}",
            "title": clean_title,
            "thesis": clean_thesis,
            "status": "exploring",
            "universe": universe.strip(),
            "signal_definition": signal_definition.strip(),
            "invalidation_criteria": invalidation_criteria.strip(),
        }
    )
    return {"status": "created", "hypothesis": hypothesis}


def _list(status: str, limit: int) -> dict:
    clean_status = _optional_status(status)
    rows = local_db.list_research_hypotheses(status=clean_status, limit=limit)
    return {"status": "ok", "count": len(rows), "hypotheses": rows}


def _detail(hypothesis_id: str) -> dict:
    hypothesis = _required_hypothesis(hypothesis_id)
    return {"status": "ok", "hypothesis": hypothesis}


def _update(
    hypothesis_id: str,
    title: str,
    thesis: str,
    status: str,
    universe: str,
    signal_definition: str,
    invalidation_criteria: str,
) -> dict:
    _required_hypothesis(hypothesis_id)
    if status.strip():
        raise ValueError("update 不允许修改 status；请使用 transition 经过晋级清单")
    changes = {
        "title": title.strip() or None,
        "thesis": thesis.strip() or None,
        "universe": universe.strip() or None,
        "signal_definition": signal_definition.strip() or None,
        "invalidation_criteria": invalidation_criteria.strip() or None,
    }
    hypothesis = local_db.update_research_hypothesis(hypothesis_id.strip(), changes)
    return {"status": "updated", "hypothesis": hypothesis}


def _link_evidence(
    hypothesis_id: str,
    evidence_type: str,
    artifact_ref: str,
    verdict: str,
    summary: str,
    metrics: dict,
) -> dict:
    clean_id = hypothesis_id.strip()
    _required_hypothesis(clean_id)
    clean_type = evidence_type.strip().lower()
    clean_verdict = verdict.strip().lower()
    if clean_type not in EVIDENCE_TYPES:
        raise ValueError(f"evidence_type 必须是: {', '.join(sorted(EVIDENCE_TYPES))}")
    if clean_verdict not in EVIDENCE_VERDICTS:
        raise ValueError(f"verdict 必须是: {', '.join(sorted(EVIDENCE_VERDICTS))}")
    if not artifact_ref.strip():
        raise ValueError("link_evidence 需要 artifact_ref")
    hypothesis = local_db.link_research_evidence(
        {
            "hypothesis_id": clean_id,
            "evidence_type": clean_type,
            "artifact_ref": artifact_ref.strip(),
            "verdict": clean_verdict,
            "summary": summary.strip(),
            "metrics": metrics,
        }
    )
    return {"status": "linked", "hypothesis": hypothesis}


def _evaluate(hypothesis_id: str) -> dict:
    hypothesis = _required_hypothesis(hypothesis_id)
    current = hypothesis["status"]
    evaluations = []
    for target in sorted(ALLOWED_TRANSITIONS[current]):
        checklist = _checklist_for_target(hypothesis, target, reason="")
        evaluations.append(
            {
                "target_status": target,
                "ready": _checklist_passes(checklist),
                "checklist": checklist,
            }
        )
    recommended = next(
        (row["target_status"] for row in evaluations if row["ready"] and row["target_status"] != "rejected"),
        None,
    )
    return {
        "status": "evaluated",
        "hypothesis_id": hypothesis["hypothesis_id"],
        "current_status": current,
        "recommended_transition": recommended,
        "evaluations": evaluations,
    }


def _transition(hypothesis_id: str, target_status: str, reason: str) -> dict:
    hypothesis = _required_hypothesis(hypothesis_id)
    current = hypothesis["status"]
    target = _optional_status(target_status)
    if not target:
        raise ValueError("transition 需要 target_status")
    if target not in ALLOWED_TRANSITIONS[current]:
        raise ValueError(f"不允许状态迁移: {current} -> {target}")
    checklist = _checklist_for_target(hypothesis, target, reason=reason)
    if not _checklist_passes(checklist):
        return {
            "status": "blocked",
            "hypothesis_id": hypothesis["hypothesis_id"],
            "current_status": current,
            "target_status": target,
            "checklist": checklist,
        }
    updated = local_db.transition_research_hypothesis(
        hypothesis["hypothesis_id"],
        from_status=current,
        to_status=target,
        reason=reason.strip() or f"晋级到 {target}",
        checklist={"items": checklist},
    )
    if updated is None:
        raise ValueError("状态已被其它进程修改，请重新 evaluate")
    return {"status": "transitioned", "hypothesis": updated, "checklist": checklist}


def _checklist_for_target(hypothesis: dict, target: str, *, reason: str) -> list[dict[str, str]]:
    if target in {"rejected", "exploring"}:
        return [_check("reason", bool(reason.strip()), "需要记录迁移原因")]
    items = [
        _check("signal_definition", bool(hypothesis.get("signal_definition")), "需要明确的信号定义"),
        _check(
            "invalidation_criteria",
            bool(hypothesis.get("invalidation_criteria")),
            "需要可验证的失效条件",
        ),
    ]
    if target == "validated":
        items.extend(
            [
                _evidence_check(hypothesis, "backtest", "需要最新跨周期回测证据为 pass"),
                _evidence_check(hypothesis, "stability", "需要最新参数稳定性证据为 pass"),
            ]
        )
    return items


def _evidence_check(hypothesis: dict, evidence_type: str, summary: str) -> dict[str, str]:
    latest = next(
        (item for item in hypothesis.get("evidence", []) if item.get("evidence_type") == evidence_type),
        None,
    )
    verdict = str((latest or {}).get("verdict") or "missing")
    return {
        "key": evidence_type,
        "status": "pass" if verdict == "pass" else "blocked",
        "summary": summary if verdict != "pass" else str(latest.get("summary") or "证据通过"),
        "artifact_ref": str((latest or {}).get("artifact_ref") or ""),
    }


def _check(key: str, passed: bool, summary: str) -> dict[str, str]:
    return {"key": key, "status": "pass" if passed else "blocked", "summary": summary}


def _checklist_passes(checklist: list[dict[str, str]]) -> bool:
    return bool(checklist) and all(item["status"] == "pass" for item in checklist)


def _required_hypothesis(hypothesis_id: str) -> dict:
    clean_id = hypothesis_id.strip()
    if not clean_id:
        raise ValueError("需要 hypothesis_id")
    hypothesis = local_db.load_research_hypothesis(clean_id)
    if hypothesis is None:
        raise ValueError(f"研究假设不存在: {clean_id}")
    return hypothesis


def _optional_status(status: str) -> str:
    clean_status = status.strip().lower()
    if clean_status and clean_status not in HYPOTHESIS_STATUSES:
        raise ValueError(f"status 必须是: {', '.join(sorted(HYPOTHESIS_STATUSES))}")
    return clean_status
