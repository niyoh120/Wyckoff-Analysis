from __future__ import annotations

import os
from datetime import date
from types import SimpleNamespace

import pytest

from workflows import recommendation_backfill as workflow
from workflows.recommendation_backfill import RecommendationBackfillRequest


def test_backfill_dry_run_does_not_require_write_context(monkeypatch, tmp_path) -> None:
    guard_calls: list[str] = []

    monkeypatch.setattr(workflow, "require_server_write_context", lambda operation: guard_calls.append(operation))
    monkeypatch.setattr(workflow, "_build_day_result", lambda day, skip_step3: _day_result(day))
    monkeypatch.setattr(workflow, "_build_payloads", lambda _dates, _results: {20260601: [_payload_row(1, 20260601)]})
    monkeypatch.setattr(workflow, "create_admin_client", lambda: object())
    monkeypatch.setattr(workflow, "_fetch_target_rows", lambda _client, _dates: [])

    status = workflow.run_recommendation_backfill(
        RecommendationBackfillRequest(
            dates=(date(2026, 6, 1),),
            output_dir=str(tmp_path),
            apply=False,
        )
    )

    assert status == 0
    assert guard_calls == []
    assert (tmp_path / "summary.json").exists()


def test_backfill_apply_replaces_only_stale_rows_for_target_dates(monkeypatch) -> None:
    client = _FakeClient()
    monkeypatch.setattr(workflow, "_refresh_performance", lambda: None)

    summary = workflow._replace_target_dates(
        client,
        {
            20260601: [
                _payload_row(1, 20260601),
                _payload_row(2, 20260601),
            ]
        },
        [
            {"id": "keep", "code": 1, "recommend_date": 20260601},
            {"id": "stale", "code": 3, "recommend_date": 20260601},
            {"id": "other-day", "code": 9, "recommend_date": 20260531},
        ],
    )

    assert summary["rows_upserted"] == 2
    assert summary["stale_deleted"] == 1
    assert client.upserts == [[_payload_row(1, 20260601), _payload_row(2, 20260601)]]
    assert client.deletes == [{"key": "id", "values": ["stale"], "filters": {}}]


def test_backfill_writes_artifacts_before_empty_date_failure(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(workflow, "_build_day_result", lambda day, skip_step3: _day_result(day))
    monkeypatch.setattr(workflow, "_build_payloads", lambda _dates, _results: {20260601: []})
    monkeypatch.setattr(workflow, "create_admin_client", lambda: object())
    monkeypatch.setattr(workflow, "_fetch_target_rows", lambda _client, _dates: [])

    with pytest.raises(RuntimeError, match="生成结果存在空日期"):
        workflow.run_recommendation_backfill(
            RecommendationBackfillRequest(
                dates=(date(2026, 6, 1),),
                output_dir=str(tmp_path),
                apply=False,
            )
        )

    assert (tmp_path / "summary.json").exists()
    assert (tmp_path / "old_rows_backup.json").exists()
    assert (tmp_path / "recommendation_tracking_20260601.json").exists()
    assert (tmp_path / "table_row_counts.json").exists()


def test_day_env_forces_readonly_write_context(monkeypatch) -> None:
    monkeypatch.setenv("WYCKOFF_WRITE_CONTEXT", "server_job")
    monkeypatch.setenv("STEP3_SKIP_LLM", "original")

    with workflow._day_env(date(2026, 6, 1), skip_step3=True):
        assert os.environ["WYCKOFF_WRITE_CONTEXT"] == "cli"
        assert os.environ["FUNNEL_DYNAMIC_POLICY"] == "off"
        assert os.environ["STEP3_SKIP_LLM"] == "1"

    assert os.environ["WYCKOFF_WRITE_CONTEXT"] == "server_job"
    assert os.environ["STEP3_SKIP_LLM"] == "original"


def test_backfill_rejects_empty_generated_dates_without_explicit_allow() -> None:
    with pytest.raises(RuntimeError, match="生成结果存在空日期"):
        workflow._validate_payloads({20260601: []}, allow_empty_date=False)

    workflow._validate_payloads({20260601: []}, allow_empty_date=True)


def test_replace_auxiliary_tables_replaces_date_scoped_rows(monkeypatch) -> None:
    client = _FakeClient()
    monkeypatch.setattr(workflow, "upsert_signal_observations", lambda rows: len(rows))

    summary = workflow._replace_auxiliary_tables(
        client,
        (date(2026, 6, 1),),
        {
            "signal_pending": [{"code": 1, "signal_date": "2026-06-01", "signal_type": "mainline"}],
            "signal_observations": [{"market": "cn", "trade_date": "2026-06-01", "code": 1}],
            "external_seed_observations": [
                {"market": "cn", "trade_date": "2026-06-01", "source": "x", "code": "000001"}
            ],
            "market_signal_daily": [{"trade_date": "2026-06-01", "benchmark_regime": "NEUTRAL"}],
            "theme_radar_snapshot": [{"trade_date": "2026-06-01", "snapshot_json": {}}],
        },
    )

    assert summary["signal_pending_inserted"] == 1
    assert summary["signal_observations_upserted"] == 1
    assert summary["external_seed_upserted"] == 1
    assert summary["market_signal_upserted"] == 1
    assert summary["theme_radar_upserted"] == 1
    assert client.deletes[:3] == [
        {"key": "signal_date", "values": ["2026-06-01"], "filters": {}},
        {"key": "trade_date", "values": ["2026-06-01"], "filters": {"market": "cn"}},
        {"key": "trade_date", "values": ["2026-06-01"], "filters": {"market": "cn"}},
    ]
    assert client.upserts[0][0]["updated_at"]


def _day_result(day: date) -> dict:
    return {
        "trade_date": day.isoformat(),
        "recommend_date": int(day.strftime("%Y%m%d")),
        "raw_count": 1,
        "write_count": 1,
        "ai_codes": [],
        "springboard_updates": {},
        "benchmark_context": {},
        "symbols_info": [{"code": "000001", "name": "平安银行", "initial_price": 10.0}],
    }


def _payload_row(code: int, rec_date: int) -> dict:
    return {"code": code, "recommend_date": rec_date, "name": f"Stock{code}", "initial_price": 10.0}


class _FakeClient:
    def __init__(self) -> None:
        self.upserts: list[list[dict]] = []
        self.inserts: list[list[dict]] = []
        self.deletes: list[dict] = []

    def table(self, _name: str):
        return _FakeQuery(self)


class _FakeQuery:
    def __init__(self, client: _FakeClient) -> None:
        self.client = client
        self.kind = ""
        self.payload: list[dict] = []
        self.filters_in: dict[str, list[object]] = {}
        self.filters_eq: dict[str, object] = {}

    def upsert(self, payload, **_kwargs):
        self.kind = "upsert"
        self.payload = list(payload)
        return self

    def insert(self, payload):
        self.kind = "insert"
        self.payload = list(payload)
        return self

    def delete(self):
        self.kind = "delete"
        return self

    def in_(self, key, values):
        self.filters_in[str(key)] = list(values)
        return self

    def eq(self, key, value):
        self.filters_eq[str(key)] = value
        return self

    def execute(self):
        if self.kind == "upsert":
            self.client.upserts.append(self.payload)
            return SimpleNamespace(data=self.payload)
        if self.kind == "insert":
            self.client.inserts.append(self.payload)
            return SimpleNamespace(data=self.payload)
        if self.kind == "delete":
            key, values = next(iter(self.filters_in.items()))
            self.client.deletes.append({"key": key, "values": values, "filters": dict(self.filters_eq)})
        return SimpleNamespace(data=[])
