from __future__ import annotations

import json

from workflows import tail_buy_policy as policy


def test_tail_buy_policy_adjustments_use_local_no_write_report(monkeypatch, tmp_path):
    report_path = tmp_path / "report.json"
    report_path.write_text(
        json.dumps(
            {
                "market": "cn",
                "shadow_diff_stats_json": {"policy_governor": {"horizon": "5"}},
                "recommendations_json": [
                    {
                        "type": "downweight",
                        "horizon": "5",
                        "target": "lps",
                        "reason": '{"action":"downweight","horizon":"5","target":"lps","weight_multiplier":0.5}',
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("TAIL_BUY_ATTRIBUTION_REPORT_JSON", str(report_path))
    monkeypatch.setattr(policy, "_load_latest_attribution_report", lambda _market: None)
    monkeypatch.setattr(policy, "log_line", lambda *_args, **_kwargs: None)

    assert policy.load_tail_buy_policy_adjustments(market="cn") == {"lps": 0.5}


def test_tail_buy_policy_adjustments_prefer_remote_report(monkeypatch, tmp_path):
    report_path = tmp_path / "report.json"
    report_path.write_text(
        json.dumps({"market": "cn", "recommendations_json": []}, ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setenv("TAIL_BUY_ATTRIBUTION_REPORT_JSON", str(report_path))
    monkeypatch.setattr(
        policy,
        "_load_latest_attribution_report",
        lambda _market: {
            "market": "cn",
            "shadow_diff_stats_json": {"policy_governor": {"horizon": "5"}},
            "recommendations_json": [
                {
                    "type": "upweight",
                    "horizon": "5",
                    "target": "sos",
                    "reason": '{"action":"upweight","horizon":"5","target":"sos","weight_multiplier":1.15}',
                }
            ],
        },
    )
    monkeypatch.setattr(policy, "log_line", lambda *_args, **_kwargs: None)

    assert policy.load_tail_buy_policy_adjustments(market="cn") == {"sos": 1.15}
