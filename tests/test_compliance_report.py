from __future__ import annotations

import json

import pandas as pd


def _sample_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "code": "600000",
                "name": "浦发银行",
                "industry": "银行",
                "track": "Trend",
                "tag": "SOS",
                "funnel_score": 0.82,
            },
            {
                "code": "300001",
                "name": "特锐德",
                "industry": "电力设备",
                "track": "Accum",
                "tag": "LPS",
                "funnel_score": 0.55,
            },
        ]
    )


def test_public_payload_is_deidentified():
    from core.compliance_report import build_public_payload

    payload = build_public_payload(
        benchmark_context={"regime": "NEUTRAL", "breadth": {"ratio_pct": 51.2}},
        selected_df=_sample_df(),
        ops_codes=["600000"],
    )

    text = json.dumps(payload, ensure_ascii=False)
    assert "600000" not in text
    assert "300001" not in text
    assert "浦发银行" not in text
    assert "特锐德" not in text
    assert "银行" in text
    assert payload["sample_stats"]["candidate_count"] == 2
    assert payload["sample_stats"]["springboard_count"] == 1


def test_public_payload_includes_market_and_etf_metrics_without_codes():
    from core.compliance_report import build_public_payload

    payload = build_public_payload(
        benchmark_context={
            "regime": "RISK_ON",
            "close": 3200.12,
            "ma50": 3150.5,
            "ma200": 3000.0,
            "breadth": {"ratio_pct": 56.7, "delta_pct": 6.2},
            "etf_enhancement": {
                "pool": 10,
                "fetched": 9,
                "l2_passed": 3,
                "strong_candidates": 2,
                "boosted_sectors": ["半导体", "证券"],
            },
            "etf_candidates": [{"code": "512480", "name": "半导体ETF", "sector": "半导体"}],
        },
        selected_df=_sample_df(),
    )

    text = json.dumps(payload, ensure_ascii=False)
    assert payload["market"]["regime_label"] == "风险偏好回升"
    assert payload["etf"]["l2_passed"] == 3
    assert payload["etf"]["strong_themes"] == ["半导体", "证券"]
    assert "512480" not in text


def test_public_payload_handles_missing_industry_column():
    from core.compliance_report import build_public_payload

    payload = build_public_payload(
        benchmark_context={"regime": "NEUTRAL"},
        selected_df=pd.DataFrame([{"code": "600000", "name": "浦发银行", "tag": "SOS"}]),
    )

    assert payload["sample_stats"]["candidate_count"] == 1
    assert payload["sector_stats"] == []


def test_validate_compliance_report_blocks_codes_names_and_action_terms():
    from core.compliance_report import validate_compliance_report

    bad = "建议关注 600000 浦发银行，明日买入并设置止损。"
    result = validate_compliance_report(bad, forbidden_names=["浦发银行"])

    assert not result.ok
    assert "contains_stock_code" in result.reasons
    assert "contains_stock_name" in result.reasons
    assert any(reason.startswith("contains_term:") for reason in result.reasons)


def test_resolve_compliance_llm_uses_efficiency(monkeypatch):
    from core.compliance_report import resolve_compliance_llm_config

    monkeypatch.setenv("EFFICIENCY_API_KEY", "eff-key")
    monkeypatch.setenv("EFFICIENCY_MODEL", "longcat")
    monkeypatch.setenv("EFFICIENCY_BASE_URL", "https://example.com/v1")

    cfg = resolve_compliance_llm_config()

    assert cfg is not None
    assert cfg.provider == "efficiency"
    assert cfg.base_url == "https://example.com/v1"


def test_generate_compliance_brief_fallback_has_no_stock_identifiers(monkeypatch):
    from core.compliance_report import generate_compliance_brief

    monkeypatch.delenv("EFFICIENCY_API_KEY", raising=False)
    monkeypatch.delenv("EFFICIENCY_MODEL", raising=False)
    monkeypatch.delenv("EFFICIENCY_BASE_URL", raising=False)

    text = generate_compliance_brief(
        benchmark_context={"regime": "RISK_OFF", "breadth": {"ratio_pct": 20}},
        selected_df=_sample_df(),
        ops_codes=["600000"],
        code_name={"600000": "浦发银行", "300001": "特锐德"},
    )

    assert "600000" not in text
    assert "300001" not in text
    assert "浦发银行" not in text
    assert "特锐德" not in text
    assert "市场观察简报" in text
    assert "大盘结构" in text
    assert "ETF温度" in text
    assert "模型" not in text
    assert "候选池" not in text
    assert "操作池" not in text


def test_generate_compliance_brief_rejects_bad_llm_output(monkeypatch):
    import core.compliance_report as cr

    monkeypatch.setenv("EFFICIENCY_API_KEY", "eff-key")
    monkeypatch.setenv("EFFICIENCY_MODEL", "mimo-v2.5-pro")
    monkeypatch.setenv("EFFICIENCY_BASE_URL", "https://example.com/v1")
    monkeypatch.setenv("STEP3_COMPLIANCE_MAX_RETRIES", "0")
    monkeypatch.setattr(cr, "call_llm", lambda **kwargs: "600000 浦发银行 可以买入")

    text = cr.generate_compliance_brief(
        benchmark_context={"regime": "NEUTRAL"},
        selected_df=_sample_df(),
        ops_codes=["600000"],
        code_name={"600000": "浦发银行"},
    )

    assert "600000" not in text
    assert "浦发银行" not in text
    assert "买入" not in text
