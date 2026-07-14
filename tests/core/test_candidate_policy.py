from __future__ import annotations

from core.candidate_policy import is_tradeable_l4_trigger_combo


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
