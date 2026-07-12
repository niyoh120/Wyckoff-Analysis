from __future__ import annotations

from workflows.reassess_profile import reassess_decision_profile

REPORT = """```json
{"decisions":[{"code":"600000","name":"浦发银行","action":"ATTACK","entry_zone":[10,12],"stop_loss":9,"confidence":0.5}]}
```"""


def test_reassess_conservative_downgrades_low_confidence_action():
    result = reassess_decision_profile(REPORT, "conservative")

    decision = result["decisions"][0]
    assert decision["final_action"] == "HOLD"
    assert decision["final_entry_zone"] == "9.8 - 11.76"
    assert decision["final_stop_loss"] == 9.45
    assert result["warnings"]


def test_reassess_aggressive_upgrades_high_confidence_hold():
    report = '{"decisions":[{"code":"600000","action":"HOLD","entry_zone":"10-12","stop_loss":9,"confidence":0.8}]}'

    result = reassess_decision_profile(report, "aggressive")

    assert result["decisions"][0]["final_action"] == "PROBE"


def test_reassess_rejects_bad_json_and_non_list_decisions():
    assert reassess_decision_profile("not-json", "balanced")["decisions"] == []
    result = reassess_decision_profile('{"decisions":{}}', "balanced")
    assert result["error"] == "decisions 字段不是列表"
