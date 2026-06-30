from __future__ import annotations

import importlib
import os
import sys
from types import ModuleType


class FakeFastMCP:
    def __init__(self, name: str) -> None:
        self.name = name

    def tool(self):
        return lambda func: func

    def run(self) -> None:
        return None


def import_mcp_server(monkeypatch):
    mcp_pkg = ModuleType("mcp")
    server_pkg = ModuleType("mcp.server")
    fastmcp_pkg = ModuleType("mcp.server.fastmcp")
    fastmcp_pkg.FastMCP = FakeFastMCP
    monkeypatch.setitem(sys.modules, "mcp", mcp_pkg)
    monkeypatch.setitem(sys.modules, "mcp.server", server_pkg)
    monkeypatch.setitem(sys.modules, "mcp.server.fastmcp", fastmcp_pkg)
    sys.modules.pop("mcp_server", None)
    return importlib.import_module("mcp_server")


def test_run_funnel_simulation_maps_main_chinext_without_mutating_env(monkeypatch):
    mcp_server = import_mcp_server(monkeypatch)
    captured_kwargs = {}

    def fake_run(*args, **kwargs):
        captured_kwargs.update(kwargs)
        return (
            True,
            [{"code": "000001"}],
            {"regime": "NEUTRAL"},
            {
                "metrics": {"layer1": 1, "all_df_map": {"000001": object()}},
                "all_df_map": {"000001": object()},
            },
        )

    fake_funnel = ModuleType("workflows.wyckoff_funnel")
    fake_funnel.run = fake_run
    monkeypatch.setitem(sys.modules, "workflows.wyckoff_funnel", fake_funnel)
    monkeypatch.setenv("FUNNEL_POOL_MODE", "manual")
    monkeypatch.setenv("FUNNEL_POOL_BOARD", "chinext")
    monkeypatch.setenv("FUNNEL_EXECUTOR_MODE", "process")

    result = mcp_server.run_funnel_simulation(board="main_chinext", limit=12)

    assert result["success"] is True
    assert captured_kwargs["pool_board"] == "main_chinext_star"
    assert captured_kwargs["pool_limit_count"] == 12
    assert captured_kwargs["executor_mode"] == "thread"
    assert result["details"] == {"metrics": {"layer1": 1}}
    assert os.environ["FUNNEL_POOL_MODE"] == "manual"
    assert os.environ["FUNNEL_POOL_BOARD"] == "chinext"
    assert os.environ["FUNNEL_EXECUTOR_MODE"] == "process"


def test_run_funnel_simulation_rejects_invalid_limit_before_pipeline(monkeypatch):
    mcp_server = import_mcp_server(monkeypatch)
    called = False

    def fake_run(*_args, **_kwargs):
        nonlocal called
        called = True
        return True, [], {}, {}

    fake_funnel = ModuleType("workflows.wyckoff_funnel")
    fake_funnel.run = fake_run
    monkeypatch.setitem(sys.modules, "workflows.wyckoff_funnel", fake_funnel)

    result = mcp_server.run_funnel_simulation(limit=3001)

    assert "limit 最大支持 3000" in result["error"]
    assert called is False
