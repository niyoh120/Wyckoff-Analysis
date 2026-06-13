"""Compliance-safe market brief generation for Step3.

The raw Wyckoff report remains the internal artifact.  The public/compliance
brief is generated from a deliberately de-identified payload: market regime,
style distribution, sector aggregates, and risk notes only.  The cheap model
is a wording assistant, not a decision maker; a deterministic validator and
template fallback own the safety boundary.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any

import pandas as pd

from integrations.llm_client import call_llm

EFFICIENCY_PROVIDER = "efficiency"
DEFAULT_MAX_OUTPUT_TOKENS = 2048

_STOCK_CODE_RE = re.compile(r"(?<!\d)\d{6}(?!\d)")
_PROHIBITED_TERMS = (
    "模型",
    "候选池",
    "操作池",
    "RAG",
    "完整研报",
    "内部流程",
    "样本入库",
    "买入",
    "卖出",
    "建仓",
    "加仓",
    "清仓",
    "减仓",
    "止损",
    "目标价",
    "参考价",
    "强烈推荐",
    "重点推荐",
    "明日买",
    "可操作",
    "PROBE",
    "ATTACK",
    "EXIT",
    "TRIM",
)


@dataclass(frozen=True)
class ComplianceLLMConfig:
    provider: str
    api_key: str
    model: str
    base_url: str
    source: str


@dataclass(frozen=True)
class ComplianceValidation:
    ok: bool
    reasons: tuple[str, ...] = ()


def _bool_env(name: str, default: bool = True) -> bool:
    raw = os.getenv(name, "")
    if not raw:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "").strip() or default)
    except Exception:
        return default


def fmt_pct(value: Any) -> str:
    num = pd.to_numeric(value, errors="coerce")
    if pd.isna(num):
        return "待更新"
    x = float(num)
    sign = "+" if x >= 0 else ""
    return f"{sign}{x:.2f}%"


def _fmt_number(value: Any, digits: int = 2) -> str:
    num = pd.to_numeric(value, errors="coerce")
    if pd.isna(num):
        return "待更新"
    return f"{float(num):.{digits}f}"


def _regime_label(regime: Any) -> str:
    mapping = {
        "RISK_ON": "风险偏好回升",
        "BEAR_REBOUND": "熊市反抽",
        "NEUTRAL": "中性震荡",
        "RISK_OFF": "防守降温",
        "CRASH": "极端风险",
        "BLACK_SWAN": "异常冲击",
    }
    key = str(regime or "NEUTRAL").strip().upper() or "NEUTRAL"
    return mapping.get(key, key)


def _safe_text(value: Any, fallback: str = "待更新") -> str:
    text = str(value or "").strip()
    return text if text else fallback


def _etf_payload(ctx: dict[str, Any]) -> dict[str, Any]:
    raw = ctx.get("etf_enhancement") or {}
    candidates = ctx.get("etf_candidates") or []
    themes = raw.get("boosted_sectors") or []
    if not themes and isinstance(candidates, list):
        themes = [str(item.get("sector", "") or "").strip() for item in candidates if isinstance(item, dict)]
    clean_themes = [x for x in dict.fromkeys(str(t).strip() for t in themes) if x]
    return {
        "pool": int(raw.get("pool") or 0),
        "fetched": int(raw.get("fetched") or 0),
        "l2_passed": int(raw.get("l2_passed") or 0),
        "strong_candidates": int(raw.get("strong_candidates") or len(candidates or [])),
        "strong_themes": clean_themes[:6],
    }


def resolve_compliance_llm_config() -> ComplianceLLMConfig | None:
    """Resolve the cheap model channel from EFFICIENCY_* variables."""

    efficiency_key = os.getenv("EFFICIENCY_API_KEY", "").strip()
    efficiency_model = os.getenv("EFFICIENCY_MODEL", "").strip()
    efficiency_base_url = os.getenv("EFFICIENCY_BASE_URL", "").strip()
    if efficiency_key and efficiency_model and efficiency_base_url:
        return ComplianceLLMConfig(
            provider=EFFICIENCY_PROVIDER,
            api_key=efficiency_key,
            model=efficiency_model,
            base_url=efficiency_base_url,
            source="efficiency",
        )

    return None


def _score_bucket(score: float) -> str:
    if score >= 0.75:
        return "高"
    if score >= 0.45:
        return "中"
    return "低"


def _bucket_phrase(bucket: Any) -> str:
    mapping = {"高": "偏高", "中": "中等", "低": "偏低"}
    return mapping.get(str(bucket or "").strip(), "待更新")


def _market_payload(ctx: dict[str, Any]) -> dict[str, Any]:
    breadth = ctx.get("breadth", {}) or {}
    return {
        "regime": str(ctx.get("regime", "NEUTRAL") or "NEUTRAL").strip().upper(),
        "regime_label": _regime_label(ctx.get("regime", "NEUTRAL")),
        "close": _fmt_number(ctx.get("close")),
        "ma50": _fmt_number(ctx.get("ma50")),
        "ma200": _fmt_number(ctx.get("ma200")),
        "ma50_slope_5d": fmt_pct(ctx.get("ma50_slope_5d")),
        "main_today_pct": fmt_pct(ctx.get("main_today_pct")),
        "recent3_cum_pct": fmt_pct(ctx.get("recent3_cum_pct")),
        "breadth_ratio": fmt_pct(breadth.get("ratio_pct")),
        "breadth_delta": fmt_pct(breadth.get("delta_pct")),
        "volume_ratio": _fmt_number(ctx.get("main_vol_ratio_5_20")),
        "volume_state": str(ctx.get("main_volume_state", "") or "").strip() or "待更新",
        "smallcap_today_pct": fmt_pct(ctx.get("smallcap_today_pct")),
        "smallcap_recent3_cum_pct": fmt_pct(ctx.get("smallcap_recent3_cum_pct")),
        "pv_summary": _safe_text(ctx.get("market_pv_summary")),
        "pv_outlook": _safe_text(ctx.get("market_pv_outlook")),
    }


def build_public_payload(
    *,
    benchmark_context: dict,
    selected_df: pd.DataFrame,
    ops_codes: list[str] | None = None,
    rag_veto_count: int = 0,
) -> dict[str, Any]:
    """Build a de-identified payload for the compliance brief."""

    ctx = benchmark_context or {}
    df = selected_df.copy() if isinstance(selected_df, pd.DataFrame) else pd.DataFrame()
    ops_set = {str(code).strip() for code in (ops_codes or []) if str(code).strip()}

    payload: dict[str, Any] = {
        "trade_date": str(ctx.get("trade_date") or ctx.get("end_trade_date") or ""),
        "market": _market_payload(ctx),
        "etf": _etf_payload(ctx),
        "sample_stats": {
            "candidate_count": int(len(df)),
            "springboard_count": int(len(ops_set)),
            "rag_veto_count": int(max(rag_veto_count, 0)),
        },
        "style_stats": {},
        "sector_stats": [],
        "risk_flags": [],
    }

    if not df.empty:
        track_series = df.get("track", pd.Series(dtype=str)).astype(str).str.strip()
        payload["style_stats"] = {
            "trend_count": int((track_series == "Trend").sum()),
            "accum_count": int((track_series == "Accum").sum()),
            "unknown_count": int((~track_series.isin(["Trend", "Accum"])).sum()),
        }

        tag_series = df.get("tag", pd.Series(dtype=str)).astype(str).str.lower()
        payload["trigger_stats"] = {
            "sos_count": int(tag_series.str.contains("sos|点火|突破", regex=True).sum()),
            "spring_count": int(tag_series.str.contains("spring", regex=True).sum()),
            "lps_count": int(tag_series.str.contains("lps", regex=True).sum()),
            "evr_count": int(tag_series.str.contains("evr", regex=True).sum()),
        }

        sec_df = df.copy()
        if "industry" in sec_df.columns:
            sec_df["industry"] = sec_df["industry"].astype(str).str.strip()
        else:
            sec_df["industry"] = ""
        sec_df = sec_df[sec_df["industry"] != ""]
        if not sec_df.empty:
            priority_raw = (
                sec_df["priority_score"]
                if "priority_score" in sec_df.columns
                else pd.Series([pd.NA] * len(sec_df), index=sec_df.index)
            )
            funnel_raw = (
                sec_df["funnel_score"]
                if "funnel_score" in sec_df.columns
                else pd.Series([pd.NA] * len(sec_df), index=sec_df.index)
            )
            score_series = pd.to_numeric(priority_raw, errors="coerce")
            score_series = score_series.where(score_series.notna(), pd.to_numeric(funnel_raw, errors="coerce"))
            sec_df["score"] = score_series.fillna(0.0)
            grouped = (
                sec_df.groupby("industry", as_index=False)
                .agg(sample_count=("industry", "count"), avg_score=("score", "mean"))
                .sort_values(["sample_count", "avg_score"], ascending=[False, False])
                .head(5)
            )
            payload["sector_stats"] = [
                {
                    "industry": str(row["industry"]),
                    "sample_count": int(row["sample_count"]),
                    "score_bucket": _score_bucket(float(row["avg_score"])),
                }
                for _, row in grouped.iterrows()
            ]

    payload["risk_flags"] = _risk_flags(payload)
    return payload


def _risk_flags(payload: dict[str, Any]) -> list[str]:
    flags = []
    regime = payload["market"]["regime"]
    if regime in {"RISK_OFF", "CRASH", "BLACK_SWAN"}:
        flags.append("市场风险偏高，弱势环境下假突破与流动性折价需要防范")
    if payload["sample_stats"]["rag_veto_count"] > 0:
        flags.append("题材持续性仍需观察，需防范潜在负面因素扰动")
    if payload["sample_stats"]["candidate_count"] <= 0:
        flags.append("结构信号不足，市场方向需要等待更多确认")
    return flags or ["避免根据单日量价变化过度外推，仍需观察需求延续性"]


def _render_payload_text(payload: dict[str, Any]) -> str:
    lines = [
        "请写成可直接转发给普通读者的市场观察，不要提模型、候选池、操作池、RAG或内部流程。",
        *_render_market_payload_lines(payload.get("market") or {}),
        *_render_etf_payload_lines(payload.get("etf") or {}),
        *_render_wyckoff_payload_lines(payload),
        *_render_sector_payload_lines(payload.get("sector_stats") or []),
        *_render_risk_payload_lines(payload.get("risk_flags") or []),
    ]
    return "\n".join(lines)


def _render_market_payload_lines(market: dict[str, Any]) -> list[str]:
    return [
        "大盘指标:",
        f"- 市场状态={market.get('regime_label', market.get('regime', 'NEUTRAL'))}",
        f"- 收盘={market.get('close')} | MA50={market.get('ma50')} | MA200={market.get('ma200')}",
        f"- 当日涨跌={market.get('main_today_pct')} | 近3日={market.get('recent3_cum_pct')}",
        f"- 广度={market.get('breadth_ratio')} | 广度变化={market.get('breadth_delta')}",
        f"- 量能={market.get('volume_state')} | 5/20量比={market.get('volume_ratio')}",
        f"- 小盘当日={market.get('smallcap_today_pct')} | 小盘近3日={market.get('smallcap_recent3_cum_pct')}",
        f"- 量价摘要={market.get('pv_summary')}",
        f"- 后续观察={market.get('pv_outlook')}",
    ]


def _render_etf_payload_lines(etf: dict[str, Any]) -> list[str]:
    themes = "、".join(etf.get("strong_themes") or []) or "暂无明显集中方向"
    return [
        "ETF指标:",
        (
            f"- ETF覆盖: 方向{etf.get('pool', 0)}，有效行情{etf.get('fetched', 0)}，"
            f"强势确认{etf.get('l2_passed', 0)}，强势方向{etf.get('strong_candidates', 0)}"
        ),
        f"- ETF强势主题={themes}",
    ]


def _render_wyckoff_payload_lines(payload: dict[str, Any]) -> list[str]:
    style = payload.get("style_stats") or {}
    trigger = payload.get("trigger_stats") or {}
    sample = payload.get("sample_stats") or {}
    return [
        "威科夫结构温度:",
        (
            "- 风格="
            f"Trend:{style.get('trend_count', 0)}, "
            f"Accum:{style.get('accum_count', 0)}, "
            f"Unknown:{style.get('unknown_count', 0)}"
        ),
        (
            "- 结构触发="
            f"强势推进确认:{trigger.get('sos_count', 0)}, "
            f"下探回收测试:{trigger.get('spring_count', 0)}, "
            f"回踩不破测试:{trigger.get('lps_count', 0)}, "
            f"缩量回撤测试:{trigger.get('evr_count', 0)}"
        ),
        f"- 结构样本数={sample.get('candidate_count', 0)}",
    ]


def _render_sector_payload_lines(sector_lines: list[dict[str, Any]]) -> list[str]:
    lines = [
        "板块热度:",
    ]
    if sector_lines:
        for item in sector_lines:
            lines.append(
                f"- {item.get('industry')} | sample_count={item.get('sample_count')} | score_bucket={item.get('score_bucket')}"
            )
    else:
        lines.append("- 无明显行业聚集")
    return lines


def _render_risk_payload_lines(risk_flags: list[str]) -> list[str]:
    lines = []
    lines.append("风险提示:")
    for item in risk_flags:
        lines.append(f"- {item}")
    return lines


def _system_prompt() -> str:
    return """你是威科夫方法市场观察简报编辑，只能基于输入的脱敏市场与ETF指标写公开市场研究摘要。

硬规则：
- 不得输出任何股票代码、股票名称、个股名单或个股排序。
- 不得给出买入、卖出、建仓、加仓、清仓、减仓、止损、目标价、参考价等交易指令。
- 不得承诺收益，不得暗示确定性上涨。
- 不要提“模型、候选池、操作池、RAG、完整研报、内部流程、样本入库”等背景词。
- 允许使用威科夫语气分析指数和ETF：供应、需求、承接、测试、吸筹、推进、回撤、派发压力。
- 若引用结构触发，必须翻成普通读者能理解的中文含义，不要堆英文缩写。
- 输出应像一篇可直接转发的短评，普通读者无需知道系统背景也能读懂。
- 输出中文 Markdown，结构固定为：大盘结构、ETF温度、威科夫解读、观察要点、风险提示。
"""


def validate_compliance_report(text: str, *, forbidden_names: list[str] | None = None) -> ComplianceValidation:
    reasons: list[str] = []
    body = text or ""
    if _STOCK_CODE_RE.search(body):
        reasons.append("contains_stock_code")
    for term in _PROHIBITED_TERMS:
        if term in body:
            reasons.append(f"contains_term:{term}")
            break
    for name in forbidden_names or []:
        clean = str(name or "").strip()
        if len(clean) >= 2 and clean in body:
            reasons.append("contains_stock_name")
            break
    return ComplianceValidation(ok=not reasons, reasons=tuple(reasons))


def render_compliance_fallback(payload: dict[str, Any]) -> str:
    market = payload.get("market") or {}
    lines = [
        "## 今日市场观察简报",
        "",
        *_fallback_market_lines(market),
        *_fallback_etf_lines(payload.get("etf") or {}),
        *_fallback_wyckoff_lines(payload),
        *_fallback_observation_lines(market, payload.get("sector_stats") or []),
        *_fallback_risk_lines(payload.get("risk_flags") or []),
    ]
    return "\n".join(lines).strip() + "\n"


def _fallback_market_lines(market: dict[str, Any]) -> list[str]:
    return [
        "### 一、大盘结构",
        (
            f"- 市场处在{market.get('regime_label', market.get('regime', 'NEUTRAL'))}状态，"
            f"当日涨跌 {market.get('main_today_pct')}，近3日累计 {market.get('recent3_cum_pct')}。"
        ),
        (
            f"- 指数收在 {market.get('close')}，相对 MA50 {market.get('ma50')}、"
            f"MA200 {market.get('ma200')} 的位置，是判断中期承接强弱的核心参照。"
        ),
        (
            f"- 市场广度 {market.get('breadth_ratio')}，广度变化 {market.get('breadth_delta')}；"
            f"量能为{market.get('volume_state')}，5/20量比 {market.get('volume_ratio')}。"
        ),
        "",
    ]


def _fallback_etf_lines(etf: dict[str, Any]) -> list[str]:
    etf_themes = "、".join(etf.get("strong_themes") or []) or "暂无明显集中方向"
    return [
        "### 二、ETF温度",
        (
            f"- ETF观察覆盖 {etf.get('pool', 0)} 个方向，"
            f"其中 {etf.get('fetched', 0)} 个有可用行情，"
            f"{etf.get('l2_passed', 0)} 个出现强势确认。"
        ),
        f"- 当前相对集中的ETF主题：{etf_themes}。",
        "",
    ]


def _fallback_wyckoff_lines(payload: dict[str, Any]) -> list[str]:
    style = payload.get("style_stats") or {}
    trigger = payload.get("trigger_stats") or {}
    return [
        "### 三、威科夫解读",
        (
            "- 当前更需要看需求是否能持续承接供应，而不是只看单日涨跌。"
            f"趋势推进结构 {style.get('trend_count', 0)}，吸筹/测试结构 {style.get('accum_count', 0)}。"
        ),
        (
            f"- 结构触发上，强势推进确认 {trigger.get('sos_count', 0)}，"
            f"下探回收测试 {trigger.get('spring_count', 0)}，"
            f"回踩不破测试 {trigger.get('lps_count', 0)}，"
            f"缩量回撤测试 {trigger.get('evr_count', 0)}。"
        ),
        "",
    ]


def _fallback_observation_lines(market: dict[str, Any], sectors: list[dict[str, Any]]) -> list[str]:
    lines = ["### 四、观察要点"]
    if sectors:
        for item in sectors[:5]:
            lines.append(f"- {item.get('industry')}：结构出现聚集，热度{_bucket_phrase(item.get('score_bucket'))}。")
    else:
        lines.append("- 暂无明显行业聚集，结构分布偏分散。")
    lines.append(f"- 量价摘要：{market.get('pv_summary')}")
    lines.append(f"- 后续观察：{market.get('pv_outlook')}")
    lines.append("")
    return lines


def _fallback_risk_lines(risk_flags: list[str]) -> list[str]:
    lines = ["### 五、风险提示"]
    for item in risk_flags:
        lines.append(f"- {item}")
    lines.extend(
        [
            "- 本简报仅用于市场研究与信息交流，不构成投资建议。",
            "- 内容可能存在遗漏或偏差，请结合公开信息独立判断。",
            "- 股市有风险，投资需谨慎。",
        ]
    )
    return lines


def _compliance_user_message(payload: dict[str, Any]) -> str:
    return (
        "请根据以下脱敏市场和ETF指标生成合规版市场观察简报。"
        "用威科夫语气解释大盘结构和ETF强弱，不要使用任何个股代码、名称或交易动作词。\n\n"
        + _render_payload_text(payload)
    )


def generate_compliance_brief(
    *,
    benchmark_context: dict,
    selected_df: pd.DataFrame,
    ops_codes: list[str] | None = None,
    code_name: dict[str, str] | None = None,
    rag_veto_count: int = 0,
) -> str:
    payload = build_public_payload(
        benchmark_context=benchmark_context,
        selected_df=selected_df,
        ops_codes=ops_codes,
        rag_veto_count=rag_veto_count,
    )
    fallback = render_compliance_fallback(payload)
    if not _bool_env("STEP3_COMPLIANCE_LLM_ENABLED", True):
        return fallback

    llm_cfg = resolve_compliance_llm_config()
    if llm_cfg is None:
        return fallback

    forbidden_names = list((code_name or {}).values())
    retries = max(_int_env("STEP3_COMPLIANCE_MAX_RETRIES", 1), 0)
    max_output_tokens = max(_int_env("STEP3_COMPLIANCE_MAX_OUTPUT_TOKENS", DEFAULT_MAX_OUTPUT_TOKENS), 512)
    user_message = _compliance_user_message(payload)
    last_reasons: tuple[str, ...] = ()
    for attempt in range(retries + 1):
        prompt = _system_prompt()
        if attempt > 0 and last_reasons:
            prompt += "\n上一版未通过合规校验，原因：" + "，".join(last_reasons) + "。请重写并严格避开。"
        try:
            text = call_llm(
                provider=llm_cfg.provider,
                model=llm_cfg.model,
                api_key=llm_cfg.api_key,
                system_prompt=prompt,
                user_message=user_message,
                base_url=llm_cfg.base_url,
                timeout=90,
                max_output_tokens=max_output_tokens,
            ).strip()
        except Exception as exc:
            print(f"[step3][compliance] {llm_cfg.source} 生成失败: {exc}")
            return fallback
        validation = validate_compliance_report(text, forbidden_names=forbidden_names)
        if validation.ok:
            print(f"[step3][compliance] 使用 {llm_cfg.source} 模型生成合规简报: {llm_cfg.model}")
            return text.rstrip() + "\n"
        last_reasons = validation.reasons
        print(
            f"[step3][compliance] 合规校验失败: attempt={attempt + 1}/{retries + 1}, reasons={','.join(last_reasons)}"
        )

    print("[step3][compliance] 已降级为确定性模板")
    return fallback
