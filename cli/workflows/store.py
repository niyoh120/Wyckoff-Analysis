"""SQLite persistence for dynamic workflow runs."""

from __future__ import annotations

import json
from typing import Any

from cli.workflows.models import WorkflowRun


def save_workflow_run(run: WorkflowRun) -> None:
    from integrations.local_db import get_db, init_db

    init_db()
    conn = get_db()
    with conn:
        conn.execute(
            """INSERT OR REPLACE INTO workflow_run
               (run_id, session_id, workflow, label, status, user_text,
                plan_json, current_step, result_summary, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
            _run_values(run),
        )


def append_workflow_event(run_id: str, event_type: str, payload: dict[str, Any]) -> None:
    from integrations.local_db import get_db, init_db

    init_db()
    conn = get_db()
    with conn:
        conn.execute(
            """INSERT INTO workflow_event (run_id, event_type, payload_json)
               VALUES (?, ?, ?)""",
            (run_id, event_type, json.dumps(payload, ensure_ascii=False, default=str)),
        )


def list_workflow_runs(limit: int = 20) -> list[dict[str, Any]]:
    from integrations.local_db import get_db, init_db

    init_db()
    cur = get_db().execute(
        """SELECT * FROM workflow_run
           ORDER BY updated_at DESC, created_at DESC
           LIMIT ?""",
        (max(1, min(limit, 200)),),
    )
    return [_decode_run_row(row) for row in cur.fetchall()]


def get_workflow_run(run_id: str) -> dict[str, Any] | None:
    from integrations.local_db import get_db, init_db

    init_db()
    cur = get_db().execute("SELECT * FROM workflow_run WHERE run_id=?", (run_id,))
    row = cur.fetchone()
    return _decode_run_row(row) if row else None


def load_workflow_events(run_id: str, limit: int = 100) -> list[dict[str, Any]]:
    from integrations.local_db import get_db, init_db

    init_db()
    cur = get_db().execute(
        """SELECT * FROM workflow_event
           WHERE run_id=?
           ORDER BY id ASC
           LIMIT ?""",
        (run_id, max(1, min(limit, 500))),
    )
    return [_decode_event_row(row) for row in cur.fetchall()]


def _run_values(run: WorkflowRun) -> tuple[Any, ...]:
    return (
        run.run_id,
        run.session_id,
        run.workflow,
        run.label,
        run.status,
        run.user_text,
        json.dumps(run.plan_payload(), ensure_ascii=False, default=str),
        run.current_step,
        run.result_summary,
    )


def _decode_run_row(row) -> dict[str, Any]:
    data = dict(row)
    data["plan"] = _loads(data.pop("plan_json", "{}"))
    return data


def _decode_event_row(row) -> dict[str, Any]:
    data = dict(row)
    data["payload"] = _loads(data.pop("payload_json", "{}"))
    return data


def _loads(raw: str) -> Any:
    try:
        return json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
