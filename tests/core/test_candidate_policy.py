from __future__ import annotations

from core.candidate_policy import cap_quality_candidates, is_tradeable_l4_trigger_combo


def test_is_tradeable_l4_trigger_combo_with_crash_watch():
    # 1. Pure crash_resilience_watch -> False
    assert is_tradeable_l4_trigger_combo(["crash_resilience_watch"]) is False

    # 2. crash_resilience_watch + spring -> True
    assert is_tradeable_l4_trigger_combo(["crash_resilience_watch", "spring"]) is True

    # 3. crash_resilience_watch + sos -> False
    assert is_tradeable_l4_trigger_combo(["crash_resilience_watch", "sos"]) is False

    # 4. Normal spring -> True
    assert is_tradeable_l4_trigger_combo(["spring"]) is True

    # 5. Normal sos -> False
    assert is_tradeable_l4_trigger_combo(["sos"]) is False


def test_quality_cap_prefers_score_and_limits_sector_concentration():
    codes = ["000001", "000002", "000003", "000004", "000005"]
    scores = {code: 100.0 - index for index, code in enumerate(codes)}
    sectors = {
        "000001": "科技",
        "000002": "科技",
        "000003": "科技",
        "000004": "医药",
        "000005": "消费",
    }

    selected, cap_dropped, sector_dropped = cap_quality_candidates(
        codes,
        scores,
        sectors,
        total_cap=3,
        max_per_sector=2,
    )

    assert selected == ["000001", "000002", "000004"]
    assert cap_dropped == ["000005"]
    assert sector_dropped == ["000003"]
