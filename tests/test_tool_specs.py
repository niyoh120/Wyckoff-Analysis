from __future__ import annotations

from cli.tools import (
    BACKGROUND_TOOLS,
    CONCURRENCY_SAFE_TOOLS,
    CONFIRM_TOOLS,
    TOOL_DISPLAY_NAMES,
    TOOL_SCHEMAS,
    TOOL_SPECS,
    ToolRegistry,
)


def test_tool_specs_cover_all_public_schemas():
    schema_names = {schema["name"] for schema in TOOL_SCHEMAS}

    assert set(TOOL_SPECS) == schema_names


def test_legacy_tool_sets_are_derived_from_specs():
    assert {name for name, spec in TOOL_SPECS.items() if spec.requires_approval} == CONFIRM_TOOLS
    assert {name for name, spec in TOOL_SPECS.items() if spec.background} == BACKGROUND_TOOLS
    assert {name for name, spec in TOOL_SPECS.items() if spec.concurrency_safe} == CONCURRENCY_SAFE_TOOLS
    assert {name: spec.display_name for name, spec in TOOL_SPECS.items()} == TOOL_DISPLAY_NAMES


def test_tool_registry_reads_runtime_behavior_from_specs():
    registry = ToolRegistry()

    assert registry.display_name("portfolio") == "持仓"
    assert registry.concurrency_safe("portfolio")
    assert registry.requires_approval("write_file")
    assert registry.is_background("run_backtest")
    assert registry.display_name("unknown_tool") == "unknown_tool"
