from __future__ import annotations

import json
from datetime import date

from workflows import strategy_attribution_policy as attribution_policy
from workflows import tail_buy_policy as policy


def test_tail_buy_policy_adjustments_use_local_no_write_report(monkeypatch, tmp_path):
    report_path = tmp_path / "report.json"
    report_path.write_text(
        json.dumps(
            {
                "market": "cn",
                "report_date": "2026-07-04",
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
    monkeypatch.setenv("STRATEGY_ATTRIBUTION_MAX_AGE_DAYS", "0")
    monkeypatch.setattr(attribution_policy, "load_latest_attribution_report", lambda _market: None)
    monkeypatch.setattr(policy, "log_line", lambda *_args, **_kwargs: None)

    assert policy.load_tail_buy_policy_adjustments(market="cn") == {"lps": 0.5}


def test_tail_buy_policy_adjustments_prefer_remote_report(monkeypatch, tmp_path):
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps({"market": "cn", "report_date": "2026-07-04"}), encoding="utf-8")
    monkeypatch.setenv("TAIL_BUY_ATTRIBUTION_REPORT_JSON", str(report_path))
    monkeypatch.setattr(
        attribution_policy,
        "load_latest_attribution_report",
        lambda _market: {
            "market": "cn",
            "report_date": "2026-07-04",
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
    monkeypatch.setenv("STRATEGY_ATTRIBUTION_MAX_AGE_DAYS", "0")

    assert policy.load_tail_buy_policy_adjustments(market="cn") == {"sos": 1.15}


def test_attribution_weights_fall_back_to_fresh_local_when_remote_is_stale(monkeypatch, tmp_path):
    report_path = tmp_path / "report.json"
    report_path.write_text(
        json.dumps(
            {
                "market": "cn",
                "report_date": "2026-07-04",
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
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("TAIL_BUY_ATTRIBUTION_REPORT_JSON", str(report_path))
    monkeypatch.setattr(
        attribution_policy,
        "load_latest_attribution_report",
        lambda _market: {
            "market": "cn",
            "report_date": "2026-06-20",
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
    )

    weights = attribution_policy.load_attribution_signal_weights(market="cn", as_of=date(2026, 7, 4))

    assert weights == {"sos": 1.15}


def test_attribution_policy_snapshot_exposes_source_and_age(monkeypatch):
    monkeypatch.setattr(
        attribution_policy,
        "load_latest_attribution_report",
        lambda _market: {
            "market": "cn",
            "report_date": "2026-07-02",
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
    )

    snapshot = attribution_policy.load_attribution_policy_snapshot(market="cn", as_of=date(2026, 7, 4))

    assert snapshot.weights == {"lps": 0.5}
    assert snapshot.source == "远端"
    assert snapshot.report_date == "2026-07-02"
    assert snapshot.age_days == 2
    assert snapshot.as_dict()["weight_count"] == 1


def test_attribution_weights_skip_stale_reports(monkeypatch, tmp_path):
    report_path = tmp_path / "report.json"
    report_path.write_text(
        json.dumps(
            {
                "market": "cn",
                "report_date": "2026-06-20",
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
    monkeypatch.setattr(attribution_policy, "load_latest_attribution_report", lambda _market: None)

    weights = attribution_policy.load_attribution_signal_weights(market="cn", as_of=date(2026, 7, 4))

    assert weights == {}
