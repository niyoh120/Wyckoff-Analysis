from core.wyckoff_engine import FunnelConfig
from workflows import funnel_layers


def test_structure_shadow_failure_does_not_block_formal_triggers(monkeypatch):
    def fail(*_args, **_kwargs):
        raise ValueError("bad structure input")

    monkeypatch.setattr(funnel_layers, "detect_structure_triggers", fail)
    formal = {"sos": [("000001", 3.0)]}

    shadow = funnel_layers._structure_shadow(["000001"], {}, FunnelConfig(), formal)

    assert formal == {"sos": [("000001", 3.0)]}
    assert shadow == {
        "mode": "observation_only",
        "status": "unavailable",
        "affects_formal_selection": False,
        "universe_count": 1,
        "reason": "ValueError",
    }
