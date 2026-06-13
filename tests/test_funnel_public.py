from __future__ import annotations

from tools.funnel_public import public_funnel_details, public_funnel_metrics


def test_public_funnel_metrics_drop_heavy_and_debug_fields():
    metrics = {
        "layer1": 10,
        "all_df_map": {"000001": object()},
        "financial_map": {"000001": {"roe": 5}},
        "_debug": {"cfg": object()},
    }

    assert public_funnel_metrics(metrics) == {"layer1": 10}


def test_public_funnel_details_drop_heavy_top_level_and_metrics_fields():
    details = {
        "selected_for_ai": ["000001"],
        "all_df_map": {"000001": object()},
        "metrics": {"layer2": 5, "all_df_map": {"000001": object()}},
    }

    assert public_funnel_details(details) == {
        "selected_for_ai": ["000001"],
        "metrics": {"layer2": 5},
    }
