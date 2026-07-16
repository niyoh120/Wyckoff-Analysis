from __future__ import annotations

from integrations import supabase_signal_pending as mod


class _Query:
    def __init__(self, existing: list[dict]) -> None:
        self.existing = existing
        self.inserted: list[dict] = []

    def select(self, *_args):
        return self

    def eq(self, *_args):
        return self

    def in_(self, *_args):
        return self

    def execute(self):
        return type("Result", (), {"data": self.existing})()

    def insert(self, rows):
        self.inserted.extend(rows)
        self.existing = []
        return self


class _Client:
    def __init__(self, existing: list[dict]) -> None:
        self.query = _Query(existing)

    def table(self, _name):
        return self.query


def test_pending_dedup_keeps_new_trade_date(monkeypatch) -> None:
    client = _Client([{"code": 600611, "signal_type": "sos", "signal_date": "2026-07-15"}])
    monkeypatch.setattr(mod, "_configured", lambda: True)
    monkeypatch.setattr(mod, "_admin", lambda: client)
    monkeypatch.setattr(mod, "require_server_write_context", lambda *_args: None)
    rows = [{"code": 600611, "signal_type": "sos", "signal_date": "2026-07-16"}]

    assert mod.insert_pending_signal_rows(rows) == 1
    assert client.query.inserted == rows


def test_pending_dedup_skips_same_trade_date(monkeypatch) -> None:
    existing = [{"code": 600611, "signal_type": "sos", "signal_date": "2026-07-16"}]
    client = _Client(existing)
    monkeypatch.setattr(mod, "_configured", lambda: True)
    monkeypatch.setattr(mod, "_admin", lambda: client)
    monkeypatch.setattr(mod, "require_server_write_context", lambda *_args: None)

    assert mod.insert_pending_signal_rows(existing) == 0
    assert client.query.inserted == []


def test_pending_dedup_skips_same_date_after_confirmation(monkeypatch) -> None:
    existing = [{"code": 600611, "signal_type": "sos", "signal_date": "2026-07-16", "status": "confirmed"}]
    client = _Client(existing)
    monkeypatch.setattr(mod, "_configured", lambda: True)
    monkeypatch.setattr(mod, "_admin", lambda: client)
    monkeypatch.setattr(mod, "require_server_write_context", lambda *_args: None)
    pending = [{"code": 600611, "signal_type": "sos", "signal_date": "2026-07-16"}]

    assert mod.insert_pending_signal_rows(pending) == 0
    assert client.query.inserted == []
