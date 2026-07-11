from __future__ import annotations

from types import SimpleNamespace

from workflows.wyckoff_funnel import _apply_ai_post_filters


def test_post_filters_sync_effective_score_before_min_score_and_rerank() -> None:
    ctx = SimpleNamespace(
        regime="NEUTRAL",
        code_to_trigger_keys={},
        code_to_total_score={"HIGH": 20.0, "LOW": 5.0},
        l2_channel_map={},
        all_df_map={},
        metrics={"min_funnel_score": 10.0},
    )
    score_map = {"HIGH": 1.0, "LOW": 15.0}

    selected, trend, accum = _apply_ai_post_filters(ctx, ["LOW", "HIGH"], ["LOW", "HIGH"], [], score_map, {})

    assert selected == ["HIGH", "LOW"]
    assert trend == ["HIGH", "LOW"]
    assert accum == []
    assert score_map["HIGH"] == 20.0


def test_post_filters_treat_invalid_scores_as_zero() -> None:
    ctx = SimpleNamespace(
        regime="NEUTRAL",
        code_to_trigger_keys={},
        code_to_total_score={"GOOD": 2.0, "BAD": "bad", "NAN": float("nan"), "INF": float("inf")},
        l2_channel_map={},
        all_df_map={},
        metrics={"min_funnel_score": 1.0},
    )
    score_map = {"GOOD": "bad", "BAD": "bad", "NAN": float("nan"), "INF": float("inf")}

    selected, trend, accum = _apply_ai_post_filters(
        ctx,
        ["BAD", "GOOD", "NAN", "INF"],
        ["BAD", "GOOD", "NAN", "INF"],
        [],
        score_map,
        {},
    )

    assert selected == ["GOOD"]
    assert trend == ["GOOD"]
    assert accum == []
    assert score_map == {"GOOD": 2.0, "BAD": 0.0, "NAN": 0.0, "INF": 0.0}


def test_post_filters_tradeable_mainline_bypasses_observe_only() -> None:
    # 1. 验证可交易主线绕过单LPS/TrendPB仅观察限制
    ctx_tradeable = SimpleNamespace(
        regime="NEUTRAL",
        code_to_trigger_keys={"000001": ["lps"]},
        code_to_total_score={"000001": 10.0},
        l2_channel_map={"000001": "吸筹通道"},
        all_df_map={},
        metrics={},
        mainline_tradeable_codes=["000001"],
    )
    score_map_1 = {"000001": 10.0}
    selected_1, _, _ = _apply_ai_post_filters(ctx_tradeable, ["000001"], ["000001"], [], score_map_1, {})
    # 应该成功绕过，不被过滤，保留在 selected_1 里
    assert "000001" in selected_1

    # 2. 验证非可交易主线（如观察或过热）不能绕过限制而被过滤
    ctx_observe_only = SimpleNamespace(
        regime="NEUTRAL",
        code_to_trigger_keys={"000001": ["lps"]},
        code_to_total_score={"000001": 10.0},
        l2_channel_map={"000001": "吸筹通道"},
        all_df_map={},
        metrics={},
        mainline_candidate_set={"000001"},  # 仅属于主线观察池，不属于 tradeable_codes
    )
    score_map_2 = {"000001": 10.0}
    selected_2, _, _ = _apply_ai_post_filters(ctx_observe_only, ["000001"], ["000001"], [], score_map_2, {})
    # 应该被 "单LPS仅观察" 过滤，不在 selected_2 里
    assert "000001" not in selected_2
