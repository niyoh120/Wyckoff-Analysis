from __future__ import annotations

import json
from types import SimpleNamespace

from integrations.supabase_recommendation import upsert_recommendations, write_recommendation_backup_artifact


class FakeSupabaseClient:
    def __init__(self, rows: list[dict] | None = None, *, fail_select: bool = False) -> None:
        self.rows = rows or []
        self.fail_select = fail_select
        self.upserts: list[list[dict]] = []

    def table(self, _name: str):
        return FakeSupabaseQuery(self)


class FakeSupabaseQuery:
    def __init__(self, client: FakeSupabaseClient) -> None:
        self.client = client
        self.kind = ""
        self.payload: list[dict] = []

    def select(self, *_args, **_kwargs):
        self.kind = "select"
        return self

    def order(self, *_args, **_kwargs):
        return self

    def range(self, *_args, **_kwargs):
        return self

    def upsert(self, payload, **_kwargs):
        self.kind = "upsert"
        self.payload = list(payload)
        return self

    def execute(self):
        if self.kind == "select":
            if self.client.fail_select:
                raise RuntimeError("transient fetch failure")
            return SimpleNamespace(data=self.client.rows)
        self.client.upserts.append(self.payload)
        return SimpleNamespace(data=self.payload)


def _enable_fake_supabase(monkeypatch, client: FakeSupabaseClient) -> None:
    monkeypatch.setattr("integrations.supabase_recommendation.is_supabase_configured", lambda: True)
    monkeypatch.setattr("integrations.supabase_recommendation._get_supabase_admin_client", lambda: client)


def test_upsert_recommendations_aborts_when_history_fetch_fails(monkeypatch):
    client = FakeSupabaseClient(fail_select=True)
    _enable_fake_supabase(monkeypatch, client)

    ok = upsert_recommendations(20260518, [{"code": "000001", "name": "Ping An", "initial_price": 10.0}])

    assert ok is False
    assert client.upserts == []


def test_upsert_recommendations_preserves_existing_recommend_count(monkeypatch):
    client = FakeSupabaseClient(
        rows=[
            {"code": 1, "recommend_count": 3, "recommend_date": 20260517},
            {"code": 1, "recommend_count": 2, "recommend_date": 20260516},
        ]
    )
    _enable_fake_supabase(monkeypatch, client)

    ok = upsert_recommendations(20260518, [{"code": "000001", "name": "Ping An", "initial_price": 10.0}])

    assert ok is True
    assert client.upserts[0][0]["recommend_count"] == 4


def test_upsert_recommendations_dedupes_same_code_same_date(monkeypatch):
    client = FakeSupabaseClient()
    _enable_fake_supabase(monkeypatch, client)

    ok = upsert_recommendations(
        20260518,
        [
            {"code": "600203", "name": "福日电子", "initial_price": 10.0, "funnel_score": 6.0},
            {"code": "600203", "name": "福日电子", "initial_price": 10.5, "funnel_score": 9.0},
        ],
    )

    assert ok is True
    assert len(client.upserts[0]) == 1
    assert client.upserts[0][0]["code"] == 600203
    assert client.upserts[0][0]["funnel_score"] == 9.0


def test_upsert_recommendations_writes_large_payload_in_chunks(monkeypatch):
    client = FakeSupabaseClient()
    _enable_fake_supabase(monkeypatch, client)
    symbols = [{"code": f"{idx:06d}", "name": f"Stock{idx}", "initial_price": 10.0} for idx in range(1, 1202)]

    ok = upsert_recommendations(20260518, symbols)

    assert ok is True
    assert [len(chunk) for chunk in client.upserts] == [500, 500, 201]


def test_write_recommendation_backup_artifact_marks_ai_and_sql(tmp_path):
    rows = [
        {
            "code": 600203,
            "name": "Furi Electronics",
            "recommend_reason": "O'Reilly setup",
            "recommend_date": 20260526,
            "initial_price": 13.55,
            "current_price": 13.55,
            "change_pct": 0.0,
            "recommend_count": 2,
            "funnel_score": 9.0,
            "is_ai_recommended": False,
            "updated_at": "2026-05-26T10:00:00+00:00",
        }
    ]

    paths = write_recommendation_backup_artifact(20260526, rows, str(tmp_path), ai_codes=["600203"])

    assert len(paths) == 2
    data = json.loads((tmp_path / "recommendation_tracking_20260526.json").read_text(encoding="utf-8"))
    assert data["row_count"] == 1
    assert data["rows"][0]["is_ai_recommended"] is True

    sql = (tmp_path / "recommendation_tracking_20260526.sql").read_text(encoding="utf-8")
    assert "insert into public.recommendation_tracking" in sql
    assert "on conflict (code, recommend_date) do update set" in sql
    assert "'O''Reilly setup'" in sql
