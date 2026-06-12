from __future__ import annotations

import pytest


def test_attribution_report_no_write_prefers_user_client(monkeypatch):
    from scripts import strategy_attribution_report as report

    marker = object()
    monkeypatch.setattr(report, "_create_user_read_client", lambda: marker)

    def fail_admin():
        raise AssertionError("admin client should not be used for no-write reports")

    monkeypatch.setattr(report, "create_admin_client", fail_admin)

    assert report._create_report_client(no_write=True) is marker


def test_attribution_report_no_write_falls_back_to_read_client(monkeypatch):
    from scripts import strategy_attribution_report as report

    marker = object()
    monkeypatch.setattr(report, "_create_user_read_client", lambda: None)
    monkeypatch.setattr(report, "create_read_client", lambda: marker)

    assert report._create_report_client(no_write=True) is marker


def test_attribution_report_write_requires_server_context(monkeypatch):
    from scripts import strategy_attribution_report as report

    monkeypatch.delenv("WYCKOFF_WRITE_CONTEXT", raising=False)
    with pytest.raises(PermissionError, match="server_job"):
        report._create_report_client(no_write=False)
