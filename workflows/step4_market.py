"""Step4 market guardrail composition."""

from __future__ import annotations

import logging

from core.market_trade_mode import normalize_regime
from integrations.supabase_market_signal import compose_market_banner, load_market_signal_daily, market_signal_readiness
from workflows.step4_text import clean_text

logger = logging.getLogger(__name__)

BENCHMARK_REGIME_SEVERITY = {
    "UNKNOWN": 3,
    "RISK_ON": 0,
    "NEUTRAL": 1,
    "BEAR_REBOUND": 2,
    "PANIC_REPAIR": 2,
    "RISK_OFF": 3,
    "CRASH": 4,
    "BLACK_SWAN": 5,
}
PREMARKET_REGIME_SEVERITY = {
    "NORMAL": 0,
    "CAUTION": 2,
    "RISK_OFF": 3,
    "BLACK_SWAN": 5,
}
EFFECTIVE_REGIME_BY_SEVERITY = {
    0: "RISK_ON",
    1: "NEUTRAL",
    2: "CAUTION",
    3: "RISK_OFF",
    4: "CRASH",
    5: "BLACK_SWAN",
}


def normalize_benchmark_regime(raw: object) -> str:
    return normalize_regime(clean_text(raw))


def normalize_premarket_regime(raw: object) -> str:
    regime = clean_text(raw).upper()
    if regime in PREMARKET_REGIME_SEVERITY:
        return regime
    return "NORMAL"


def resolve_effective_market_regime(benchmark_regime: object, premarket_regime: object) -> str:
    benchmark_norm = normalize_benchmark_regime(benchmark_regime)
    premarket_norm = normalize_premarket_regime(premarket_regime)
    if benchmark_norm == "UNKNOWN" and premarket_norm == "NORMAL":
        return "UNKNOWN"
    severity = max(
        BENCHMARK_REGIME_SEVERITY.get(benchmark_norm, 1),
        PREMARKET_REGIME_SEVERITY.get(premarket_norm, 0),
    )
    return EFFECTIVE_REGIME_BY_SEVERITY.get(severity, benchmark_norm)


def load_market_signal_for_trade_date(trade_date: str) -> dict[str, object] | None:
    try:
        return load_market_signal_daily(trade_date)
    except Exception as e:
        logger.warning("读取 market_signal_daily 失败: trade_date=%s, err=%s", trade_date, e)
        return None


def _benchmark_regime_and_readiness(
    row: dict[str, object], benchmark_context: dict | None, trade_date: str
) -> tuple[str, dict[str, str]]:
    readiness = market_signal_readiness(row, trade_date)
    context_regime = (benchmark_context or {}).get("regime")
    regime = normalize_benchmark_regime(context_regime or row.get("benchmark_regime"))
    if not context_regime and readiness["status"] != "ready":
        regime = "UNKNOWN"
    return regime, readiness


def build_market_guardrail(
    *,
    trade_date: str,
    benchmark_context: dict | None,
    market_signal_row: dict[str, object] | None,
    buy_block_regimes: set[str],
) -> tuple[str, str, str]:
    row = dict(market_signal_row or {})
    benchmark_regime, readiness = _benchmark_regime_and_readiness(row, benchmark_context, trade_date)
    premarket_regime = normalize_premarket_regime(row.get("premarket_regime"))
    effective_regime = resolve_effective_market_regime(benchmark_regime, premarket_regime)

    if benchmark_context:
        row.update(
            {
                "benchmark_regime": benchmark_regime,
                "main_index_close": benchmark_context.get("close"),
                "main_index_ma50": benchmark_context.get("ma50"),
                "main_index_ma200": benchmark_context.get("ma200"),
                "main_index_recent3_cum_pct": benchmark_context.get("recent3_cum_pct"),
                "main_index_today_pct": benchmark_context.get("main_today_pct"),
                "smallcap_close": benchmark_context.get("smallcap_close"),
                "smallcap_recent3_cum_pct": benchmark_context.get("smallcap_recent3_cum_pct"),
            }
        )
    row["premarket_regime"] = premarket_regime

    banner = compose_market_banner(row)
    panic_reasons = [
        str(x).strip() for x in ((benchmark_context or {}).get("panic_reasons", []) or []) if str(x).strip()
    ]
    premarket_reasons = [str(x).strip() for x in (row.get("premarket_reasons", []) or []) if str(x).strip()]

    lines = [
        "[全局风控]",
        f"trade_date={trade_date}, effective_regime={effective_regime}, "
        f"benchmark_regime={benchmark_regime}, premarket_regime={premarket_regime}",
        f"market_data_status={readiness['status']}, reason={readiness['reason']}",
    ]
    if benchmark_context:
        lines.append(
            f"benchmark_close={benchmark_context.get('close')}, ma50={benchmark_context.get('ma50')}, "
            f"ma200={benchmark_context.get('ma200')}, recent3={benchmark_context.get('recent3_pct')}, "
            f"cum3={benchmark_context.get('recent3_cum_pct')}, smallcap_today={benchmark_context.get('smallcap_today_pct')}"
        )
    if effective_regime in buy_block_regimes:
        lines.append("⚠️ 全局风控一票否决：OMS 将强制拦截全部买入动作（仅允许 HOLD/TRIM/EXIT）。")
    elif premarket_regime == "CAUTION":
        lines.append("⚠️ 盘前情绪扰动已触发：OMS 会自动收紧追价阈值并优先防守。")
    if panic_reasons:
        lines.append("panic_reasons=" + " | ".join(panic_reasons))
    if premarket_reasons:
        lines.append("premarket_reasons=" + " | ".join(premarket_reasons))
    lines.append("")

    posture_name = clean_text(banner.get("market_posture_name"))
    action_phrase = clean_text(banner.get("action_phrase"))
    system_market_view = f"系统风控：{effective_regime}"
    if posture_name:
        system_market_view += f" / {posture_name}"
    view_parts = [f"收盘={benchmark_regime}"]
    if premarket_regime != "NORMAL":
        view_parts.append(f"盘前={premarket_regime}")
    if action_phrase:
        view_parts.append(action_phrase)
    if view_parts:
        system_market_view += " | " + "；".join(view_parts)

    return (effective_regime, "\n".join(lines), system_market_view)
