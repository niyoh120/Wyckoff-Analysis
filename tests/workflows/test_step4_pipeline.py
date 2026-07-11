from __future__ import annotations

from workflows.step4_pipeline import _step4_candidate_meta


def test_step4_candidate_meta_allows_springboard_and_top_funnel(monkeypatch):
    # Mocking environment variable
    monkeypatch.setenv("STEP4_TOP_FUNNEL_CANDIDATES_COUNT", "2")
    monkeypatch.setenv("STEP4_REQUIRE_CONFIRMED_BUY_CANDIDATE", "1")

    symbols_info = [
        # 1. 确认的, 分数高, 但不在 springboard_codes 里 (应通过 top_n=2 获准)
        {"code": "000001", "confirm_status": "confirmed", "priority_score": 95},
        # 2. 确认的, 分数较高, 也不在 springboard_codes 里 (应通过 top_n=2 获准)
        {"code": "000002", "tag": "二次确认", "score": 90},
        # 3. 确认的, 分数低, 不在 springboard_codes 里 (应被 top_n=2 拦截)
        {"code": "000003", "recommend_reason": "confirmed", "priority_score": 50},
        # 4. 未确认的, 但在 springboard_codes 里 (因为 require_confirmed=1，应被拦截)
        {"code": "000004", "tag": "pending", "priority_score": 88},
        # 5. 确认的, 且在 springboard_codes 里 (应通过 allowed_set 获准)
        {"code": "000005", "tag": "confirmed", "priority_score": 75},
    ]

    selected, blocked = _step4_candidate_meta(symbols_info, step3_springboard_codes=["000004", "000005"])

    selected_codes = {item["code"] for item in selected}
    # 000001: 获准 (Top 1)
    # 000002: 获准 (Top 2)
    # 000005: 获准 (Springboard + confirmed)
    assert selected_codes == {"000001", "000002", "000005"}
    # 000004 是待确认，所以在 require_confirmed 下被 block 1 次
    assert blocked == 1


def test_step4_candidate_meta_with_top_n_disabled_by_default(monkeypatch):
    # By default, STEP4_TOP_FUNNEL_CANDIDATES_COUNT should not be set (defaults to 0 / disabled)
    monkeypatch.delenv("STEP4_TOP_FUNNEL_CANDIDATES_COUNT", raising=False)
    monkeypatch.setenv("STEP4_REQUIRE_CONFIRMED_BUY_CANDIDATE", "1")

    symbols_info = [
        {"code": "000001", "confirm_status": "confirmed", "priority_score": 95},
        {"code": "000005", "tag": "confirmed", "priority_score": 75},
    ]

    # Only 000005 is in springboard_codes, 000001 is NOT. With top_n=0, 000001 should be blocked.
    selected, blocked = _step4_candidate_meta(symbols_info, step3_springboard_codes=["000005"])
    selected_codes = {item["code"] for item in selected}
    assert selected_codes == {"000005"}
    assert blocked == 0


def test_step4_candidate_meta_with_illegal_config_values(monkeypatch):
    # Test illegal config values like 'not-a-number' or negative values
    monkeypatch.setenv("STEP4_TOP_FUNNEL_CANDIDATES_COUNT", "invalid-value")
    symbols_info = [
        {"code": "000001", "confirm_status": "confirmed", "priority_score": 95},
        {"code": "000005", "tag": "confirmed", "priority_score": 75},
    ]
    selected, blocked = _step4_candidate_meta(symbols_info, step3_springboard_codes=["000005"])
    selected_codes = {item["code"] for item in selected}
    # Should fallback to 0 safely without crashing and only allow springboard codes
    assert selected_codes == {"000005"}

    # Test negative value
    monkeypatch.setenv("STEP4_TOP_FUNNEL_CANDIDATES_COUNT", "-5")
    selected, blocked = _step4_candidate_meta(symbols_info, step3_springboard_codes=["000005"])
    selected_codes = {item["code"] for item in selected}
    assert selected_codes == {"000005"}
