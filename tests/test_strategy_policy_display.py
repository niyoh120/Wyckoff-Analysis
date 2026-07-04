from __future__ import annotations

from core.strategy_policy_display import (
    format_policy_meta_text,
    format_policy_weight_text,
    parse_policy_weight_key,
    policy_weight_rows,
)


def test_parse_policy_weight_key_preserves_scoped_context() -> None:
    parsed = parse_policy_weight_key("lps|regime=RISK_ON|lane=trend_pullback|entry=wyckoff_structure")

    assert parsed == {
        "signal_type": "lps",
        "scope": {
            "regime": "RISK_ON",
            "lane": "trend_pullback",
            "entry_type": "wyckoff_structure",
        },
    }


def test_policy_weight_rows_include_label_and_direction() -> None:
    rows = policy_weight_rows({"lps|regime=RISK_ON|lane=trend_pullback": 0.5, "sos": 1.15})

    assert rows[0]["label"] == "lps[regime=RISK_ON, lane=trend_pullback]"
    assert rows[0]["direction"] == "down"
    assert rows[1]["label"] == "sos"
    assert rows[1]["direction"] == "up"


def test_format_policy_weight_text_sanitizes_invalid_values() -> None:
    assert format_policy_weight_text({"bad": "bad", "nan": float("nan")}, delimiter="；") == "bad×1.00；nan×1.00"


def test_format_policy_meta_text_surfaces_active_scope() -> None:
    assert (
        format_policy_meta_text(
            {
                "source": "远端",
                "report_date": "2026-07-04",
                "horizon": "5",
                "execution_policy": "on",
                "execution_scope": "tail_buy_and_funnel",
                "tail_buy_weights_active": True,
                "funnel_shadow_weights_active": True,
                "funnel_formal_weights_active": True,
            }
        )
        == "（远端, report=2026-07-04, h=5, mode=on, scope=tail_buy_and_funnel, active=尾盘+正式漏斗）"
    )
