"""Public premarket risk brief generation.

The brief is safe for the public CF Pages surface: it only uses market-level
signals and rejects stock identifiers, personal portfolio wording, and direct
trading instructions.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from utils.safe import finite_float

ALLOWED_TONES = ("乐观", "谨慎乐观", "谨慎", "保守", "恶劣")
_STOCK_CODE_RE = re.compile(r"(?<!\d)\d{6}(?!\d)")
_PROHIBITED_TERMS = (
    "持仓",
    "账户",
    "成本",
    "仓位",
    "个股",
    "股票代码",
    "买入",
    "卖出",
    "建仓",
    "加仓",
    "减仓",
    "清仓",
    "止损",
    "目标价",
    "推荐",
    "满仓",
)
PublicBriefLlmCaller = Callable[..., str]


@dataclass(frozen=True)
class PublicBriefLlmConfig:
    routes: tuple[dict[str, str], ...] = ()
    timeout_seconds: int = 45
    max_output_tokens: int = 512


def _fmt_pct(raw: Any) -> str:
    value = finite_float(raw)
    if value is None:
        return "待更新"
    return f"{value:+.2f}%"


def _brief_tone(regime: str) -> str:
    return {
        "UNKNOWN": "保守",
        "NORMAL": "谨慎",
        "CAUTION": "保守",
        "RISK_OFF": "保守",
        "BLACK_SWAN": "恶劣",
    }.get(str(regime or "").strip().upper(), "谨慎")


def build_public_premarket_payload(
    *,
    a50: dict,
    vix: dict,
    regime: str,
    reasons: list[str],
    market_signal: dict | None = None,
) -> dict[str, Any]:
    market_signal = market_signal or {}
    return {
        "premarket_regime": str(regime or "NORMAL").strip().upper(),
        "premarket_reasons": [str(x) for x in reasons if str(x).strip()][:5],
        "a50": {
            "date": a50.get("date"),
            "pct_chg": _fmt_pct(a50.get("pct_chg")),
            "source": a50.get("source"),
            "ok": bool(a50.get("ok")),
        },
        "vix": {
            "date": vix.get("date"),
            "close": finite_float(vix.get("close")),
            "pct_chg": _fmt_pct(vix.get("pct_chg")),
            "source": vix.get("source"),
            "ok": bool(vix.get("ok")),
        },
        "domestic_context": {
            "benchmark_regime": str(market_signal.get("benchmark_regime") or "UNKNOWN").strip().upper(),
            "main_index_today_pct": _fmt_pct(market_signal.get("main_index_today_pct")),
            "recent3_cum_pct": _fmt_pct(market_signal.get("main_index_recent3_cum_pct")),
            "banner_title": str(market_signal.get("banner_title") or "").strip(),
            "banner_message": str(market_signal.get("banner_message") or "").strip(),
        },
    }


def fallback_public_brief(payload: dict[str, Any]) -> dict[str, Any]:
    regime = str(payload.get("premarket_regime") or "NORMAL").strip().upper()
    domestic = payload.get("domestic_context") or {}
    benchmark = str(domestic.get("benchmark_regime") or "UNKNOWN")
    a50_pct = (payload.get("a50") or {}).get("pct_chg") or "待更新"
    vix_pct = (payload.get("vix") or {}).get("pct_chg") or "待更新"
    title = {
        "UNKNOWN": "盘前关键数据待确认，暂停新增风险",
        "NORMAL": "盘前环境整体平稳，等待开盘确认",
        "CAUTION": "隔夜扰动出现，盘前先保持谨慎",
        "RISK_OFF": "隔夜风险偏好转冷，盘前以防守为先",
        "BLACK_SWAN": "隔夜恐慌冲击抬升，盘前严控节奏",
    }.get(regime, "盘前环境待确认，先观察开盘承接")
    message = (
        f"昨日场内水温为 {benchmark}，盘前 A50 {a50_pct}，VIX {vix_pct}。"
        "今日重点观察开盘承接、指数量能与风险偏好是否同步修复；在信号未统一前，优先保持节奏和纪律。"
    )
    return {
        "banner_title": title,
        "banner_message": message,
        "banner_tone": _brief_tone(regime),
        "llm_used": False,
        "provider": "fallback",
        "model": "",
        "validation_reasons": [],
    }


def validate_public_brief(brief: dict[str, Any]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    title = str(brief.get("banner_title") or "").strip()
    message = str(brief.get("banner_message") or "").strip()
    tone = str(brief.get("banner_tone") or "").strip()
    text = f"{title}\n{message}"
    if not title or len(title) > 48:
        reasons.append("bad_title")
    if not message or len(message) > 220:
        reasons.append("bad_message")
    if tone not in ALLOWED_TONES:
        reasons.append("bad_tone")
    if _STOCK_CODE_RE.search(text):
        reasons.append("contains_stock_code")
    for term in _PROHIBITED_TERMS:
        if term in text:
            reasons.append(f"contains_term:{term}")
    return not reasons, reasons


def _extract_json_object(raw: str) -> dict[str, Any]:
    text = str(raw or "").strip()
    if not text:
        raise ValueError("empty llm output")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.S)
        if not match:
            raise
        parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise ValueError("llm output is not object")
    return parsed


def _system_prompt() -> str:
    return (
        "你是量化策略 SaaS 的公共盘前风控摘要撰写助手。"
        "只根据市场级数据生成通用说明，不涉及任何个人持仓、账户、个股、股票代码或买卖指令。"
        '输出严格 JSON：{"banner_title":"不超过48字","banner_message":"不超过220字","banner_tone":"乐观|谨慎乐观|谨慎|保守|恶劣"}。'
    )


def generate_public_premarket_brief(
    *,
    a50: dict,
    vix: dict,
    regime: str,
    reasons: list[str],
    market_signal: dict | None = None,
    llm_config: PublicBriefLlmConfig | None = None,
    llm_caller: PublicBriefLlmCaller | None = None,
) -> dict[str, Any]:
    payload = build_public_premarket_payload(
        a50=a50,
        vix=vix,
        regime=regime,
        reasons=reasons,
        market_signal=market_signal,
    )
    fallback = fallback_public_brief(payload)
    user_message = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    config = llm_config or PublicBriefLlmConfig()
    if llm_caller is None:
        return fallback
    for route in config.routes:
        try:
            raw = llm_caller(
                provider=route["provider"],
                model=route["model"],
                api_key=route["api_key"],
                base_url=route.get("base_url") or None,
                system_prompt=_system_prompt(),
                user_message=user_message,
                timeout=config.timeout_seconds,
                max_output_tokens=config.max_output_tokens,
            )
            brief = _extract_json_object(raw)
            ok, validation_reasons = validate_public_brief(brief)
            if not ok:
                fallback["validation_reasons"] = validation_reasons
                continue
            return {
                "banner_title": str(brief["banner_title"]).strip(),
                "banner_message": str(brief["banner_message"]).strip(),
                "banner_tone": str(brief["banner_tone"]).strip(),
                "llm_used": True,
                "provider": route["provider"],
                "model": route["model"],
                "validation_reasons": [],
            }
        except Exception as exc:
            fallback["validation_reasons"] = [f"llm_error:{type(exc).__name__}"]
    return fallback
