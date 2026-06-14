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
    assert "ask_user" not in schema_names


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


def test_tool_registry_filters_schemas_by_workflow_scope():
    registry = ToolRegistry()

    names = {schema["name"] for schema in registry.schemas({"portfolio", "ask_user_question"})}

    assert names == {"portfolio", "ask_user_question"}


def test_ask_user_question_uses_question_callback():
    registry = ToolRegistry()
    observed = {}

    def _answer(question, options, allow_free_text, default_answer):
        observed["question"] = question
        observed["options"] = options
        observed["allow_free_text"] = allow_free_text
        observed["default_answer"] = default_answer
        return "近一年"

    registry.set_ask_user_question_callback(_answer)

    result = registry.execute(
        "ask_user_question",
        {
            "question": "回测区间？",
            "options": ["近半年", "近一年"],
            "allow_free_text": False,
            "default_answer": "近半年",
        },
    )

    assert result["status"] == "answered"
    assert result["answer"] == "近一年"
    assert observed == {
        "question": "回测区间？",
        "options": ["近半年", "近一年"],
        "allow_free_text": False,
        "default_answer": "近半年",
    }
