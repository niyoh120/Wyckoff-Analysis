from __future__ import annotations

import os

from agents import tool_context


def test_cloud_credentials_do_not_fall_back_to_local_or_environment(monkeypatch):
    ctx = tool_context.ToolContext({"user_id": "user-a", "access_token": "jwt"})
    monkeypatch.setattr(tool_context, "load_user_credentials", lambda _uid: {})
    monkeypatch.setattr("integrations.local_auth.load_config", lambda: {"tushare_token": "operator-local"})
    monkeypatch.setenv("TUSHARE_TOKEN", "operator-env")

    assert tool_context.get_credential(ctx, "tushare_token", "TUSHARE_TOKEN") == ""


def test_cloud_tushare_token_is_context_local(monkeypatch):
    ctx = tool_context.ToolContext({"user_id": "user-a", "access_token": "jwt"})
    monkeypatch.setattr(tool_context, "load_user_credentials", lambda _uid: {"tushare_token": "user-token"})
    monkeypatch.setenv("TUSHARE_TOKEN", "operator-token")

    tool_context.ensure_tushare_token(ctx)

    assert os.environ["TUSHARE_TOKEN"] == "operator-token"
    assert ctx.state["tushare_token"] == "user-token"
    from integrations.tushare_client import has_tushare_token

    assert has_tushare_token()
