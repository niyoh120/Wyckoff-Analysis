"""
Supabase 最新交易日市场信号读写

用途：
1) 定时任务写入 A50 / VIX / 大盘水温
2) Web 端读取最新交易日市场信号并渲染全局提示栏
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from typing import Any

from supabase import Client

from core.constants import TABLE_MARKET_SIGNAL_DAILY
from integrations.supabase_base import create_admin_client as _get_supabase_admin_client
from integrations.supabase_base import create_read_client as _get_supabase_read_client
from integrations.supabase_base import is_admin_configured as is_supabase_admin_configured
from integrations.supabase_base import require_server_write_context
from utils.safe import finite_float as _safe_float

logger = logging.getLogger(__name__)


def _normalize_trade_date(raw: Any) -> str:
    if isinstance(raw, date):
        return raw.isoformat()
    text = str(raw or "").strip()
    if len(text) >= 10:
        return text[:10]
    return text


def market_signal_readiness(row: dict[str, Any] | None, expected_trade_date: date | str) -> dict[str, str]:
    expected = _normalize_trade_date(expected_trade_date)
    if not row:
        return {"status": "missing", "reason": "market_signal_daily 无当日记录"}
    actual = _normalize_trade_date(row.get("trade_date"))
    if not actual or actual != expected:
        return {"status": "stale", "reason": f"市场信号日期 {actual or '-'} != {expected}"}
    benchmark = str(row.get("benchmark_regime") or "").strip().upper()
    if not benchmark:
        return {"status": "partial", "reason": "当日盘后 benchmark 尚未就绪"}
    return {"status": "ready", "reason": "当日盘后 benchmark 已就绪"}


def _format_signed_pct(raw: Any) -> str:
    value = _safe_float(raw)
    if value is None:
        return "--"
    return f"{value:+.2f}%"


def _format_plain(raw: Any, digits: int = 2) -> str:
    value = _safe_float(raw)
    if value is None:
        return "--"
    return f"{value:.{digits}f}"


def _benchmark_regime_desc(regime: str) -> str:
    mapping = {
        "RISK_ON": "偏强",
        "NEUTRAL": "中性",
        "RISK_OFF": "偏弱",
        "CRASH": "极弱",
        "PANIC_REPAIR": "修复候选",
        "PANIC_REPAIR_CONFIRMED": "修复成立",
        "BLACK_SWAN": "极端恶劣",
        "UNKNOWN": "待确认",
    }
    return mapping.get(str(regime or "").strip().upper(), "待确认")


def _premarket_regime_desc(regime: str) -> str:
    mapping = {
        "NORMAL": "平稳",
        "CAUTION": "情绪冲击",
        "RISK_OFF": "转冷",
        "BLACK_SWAN": "急剧恶化",
    }
    return mapping.get(str(regime or "").strip().upper(), "待确认")


def _normalize_benchmark_slot(regime: str) -> str:
    normalized = str(regime or "").strip().upper()
    if not normalized:
        return "UNKNOWN"
    if normalized == "RISK_ON":
        return "RISK_ON"
    if normalized == "NEUTRAL":
        return "NEUTRAL"
    if normalized in {"CRASH", "BLACK_SWAN"}:
        return "CRASH"
    return "RISK_OFF"


def _normalize_premarket_slot(regime: str) -> str:
    normalized = str(regime or "").strip().upper()
    if normalized in {"BLACK_SWAN", "RISK_OFF", "CAUTION", "NORMAL"}:
        return normalized
    return "NORMAL"


def _benchmark_state_sentence(regime: str) -> str:
    mapping = {
        "RISK_ON": "盘后主线仍偏强",
        "NEUTRAL": "盘后市场仍在震荡观察",
        "RISK_OFF": "盘后市场已偏弱",
        "CRASH": "盘后市场已处在明显防守区",
        "PANIC_REPAIR": "盘后市场出现修复候选，仍需次日确认",
        "PANIC_REPAIR_CONFIRMED": "盘后修复已通过次日广度与价格确认",
        "BLACK_SWAN": "盘后市场已处在明显防守区",
        "UNKNOWN": "盘后市场状态仍待确认",
    }
    return mapping.get(str(regime or "").strip().upper(), "盘后市场状态仍待确认")


def _premarket_state_sentence(regime: str) -> str:
    mapping = {
        "NORMAL": "隔夜外部冲击相对平稳",
        "CAUTION": "隔夜情绪扰动已经出现",
        "RISK_OFF": "隔夜风险偏好明显转冷",
        "BLACK_SWAN": "隔夜恐慌冲击正在抬升",
    }
    return mapping.get(str(regime or "").strip().upper(), "隔夜外部环境仍待确认")


STRUCTURED_MARKET_SIGNAL_FIELDS = {
    "benchmark_slot",
    "premarket_slot",
    "market_posture_code",
    "market_posture_name",
    "wind_phrase",
    "water_phrase",
    "action_phrase",
}
CUSTOM_BANNER_FIELDS = ("banner_title", "banner_message", "banner_tone")
BENCHMARK_MERGE_FIELDS = (
    "trade_date",
    "benchmark_regime",
    "main_index_code",
    "main_index_close",
    "main_index_ma50",
    "main_index_ma200",
    "main_index_recent3_cum_pct",
    "main_index_today_pct",
    "smallcap_index_code",
    "smallcap_close",
    "smallcap_recent3_cum_pct",
)
PREMARKET_MERGE_FIELDS = ("premarket_regime", "premarket_reasons")
A50_MERGE_FIELDS = ("a50_value_date", "a50_source", "a50_close", "a50_pct_chg")
VIX_MERGE_FIELDS = ("vix_value_date", "vix_source", "vix_close", "vix_pct_chg")


MARKET_BANNER_MATRIX: dict[str, dict[str, dict[str, str]]] = {
    "BLACK_SWAN": {
        "RISK_ON": {
            "posture_code": "DEFENSIVE",
            "posture_name": "防守优先",
            "tone": "保守",
            "title": "亲爱的投资者，最新交易日大盘偏强，但隔夜恐慌冲击已显著抬升。",
            "wind": "盘面风向正在由进攻转向防守",
            "water": "避险资金正在快速回流",
            "action": "先收缩防线，暂停激进追价，只保留最确定的观察与应对",
        },
        "NEUTRAL": {
            "posture_code": "HARD_DEFENSE",
            "posture_name": "严防死守",
            "tone": "恶劣",
            "title": "亲爱的投资者，最新交易日水温中性，但隔夜恐慌冲击已经压过试探空间。",
            "wind": "市场风向明显偏冷",
            "water": "资金更倾向于防守和撤离",
            "action": "以防守为先，耐心等待风险释放，不要伸手接刀",
        },
        "RISK_OFF": {
            "posture_code": "HARD_DEFENSE",
            "posture_name": "严防死守",
            "tone": "恶劣",
            "title": "亲爱的投资者，最新交易日内外部信号共振转弱，当前先守再说。",
            "wind": "弱势风向正在共振",
            "water": "流动性更偏向撤退而不是进攻",
            "action": "先把风险控制放在首位，尽量减少无谓出手",
        },
        "CRASH": {
            "posture_code": "HARD_DEFENSE",
            "posture_name": "严防死守",
            "tone": "恶劣",
            "title": "亲爱的投资者，最新交易日已处在高压防守区，当前严禁激进出手。",
            "wind": "恐慌风暴仍在场内回荡",
            "water": "避险资金继续占上风",
            "action": "严格防守，等待市场重新给出清晰修复信号",
        },
    },
    "RISK_OFF": {
        "RISK_ON": {
            "posture_code": "DEFENSIVE",
            "posture_name": "收缩防线",
            "tone": "保守",
            "title": "亲爱的投资者，最新交易日大盘偏强，但隔夜风险偏好已经转冷。",
            "wind": "盘面风向仍在上方，但阻力开始变大",
            "water": "资金从全面进攻转向去弱留强",
            "action": "控制节奏和仓位，只跟随最强、最清晰的主线机会",
        },
        "NEUTRAL": {
            "posture_code": "DEFENSIVE",
            "posture_name": "收缩防线",
            "tone": "保守",
            "title": "亲爱的投资者，最新交易日方向尚未完全明朗，隔夜风险偏冷需要优先处理。",
            "wind": "市场风向偏向谨慎",
            "water": "资金更愿意先看清再行动",
            "action": "先稳住节奏，多看少动，等待更高胜率的确认点",
        },
        "RISK_OFF": {
            "posture_code": "DEFENSIVE",
            "posture_name": "收缩防线",
            "tone": "保守",
            "title": "亲爱的投资者，最新交易日市场已偏弱，隔夜风险继续转冷。",
            "wind": "弱势风向仍在延续",
            "water": "资金持续往防守端聚集",
            "action": "以防守仓位为主，避免在弱势环境中频繁试错",
        },
        "CRASH": {
            "posture_code": "HARD_DEFENSE",
            "posture_name": "严防死守",
            "tone": "恶劣",
            "title": "亲爱的投资者，最新交易日市场处在防守区，隔夜风险继续加码。",
            "wind": "下行压力没有解除",
            "water": "场内资金仍以撤退为主",
            "action": "严格收缩战线，等风险释放充分后再讨论进攻",
        },
    },
    "CAUTION": {
        "RISK_ON": {
            "posture_code": "CONTROLLED_ATTACK",
            "posture_name": "控制试探",
            "tone": "谨慎乐观",
            "title": "亲爱的投资者，最新交易日大盘仍偏强，但隔夜情绪出现扰动。",
            "wind": "做多风向还在，但节奏开始放缓",
            "water": "资金仍会流向强者，只是不再全面扩散",
            "action": "可以继续顺势跟随，但要用更轻的仓位去做更高胜率的确认机会",
        },
        "NEUTRAL": {
            "posture_code": "PATIENT_OBSERVE",
            "posture_name": "耐心观察",
            "tone": "谨慎",
            "title": "亲爱的投资者，最新交易日水温中性，隔夜情绪扰动要求先看清方向。",
            "wind": "市场风向仍在摇摆",
            "water": "资金在试探，暂未形成明确合力",
            "action": "盘中沉着应对，先观察，再等待最清晰的结构确认",
        },
        "RISK_OFF": {
            "posture_code": "DEFENSIVE",
            "posture_name": "收缩防线",
            "tone": "保守",
            "title": "亲爱的投资者，最新交易日市场偏弱，隔夜情绪扰动会继续放大压力。",
            "wind": "偏弱风向暂未改变",
            "water": "资金更倾向于收缩而非扩张",
            "action": "保持防守姿态，只做极少量、极高确定性的试探",
        },
        "CRASH": {
            "posture_code": "HARD_DEFENSE",
            "posture_name": "严防死守",
            "tone": "恶劣",
            "title": "亲爱的投资者，最新交易日仍在防守区，隔夜情绪扰动不宜低估。",
            "wind": "弱势风向占主导",
            "water": "资金风险偏好仍在收缩",
            "action": "不急于出手，先把仓位纪律和止损纪律放在第一位",
        },
    },
    "NORMAL": {
        "RISK_ON": {
            "posture_code": "FULL_ATTACK",
            "posture_name": "顺势进攻",
            "tone": "乐观",
            "title": "亲爱的投资者，最新交易日内外部信号共振偏强。",
            "wind": "做多风向仍在发酵",
            "water": "资金仍在向强势主线集中",
            "action": "顺势跟随，但只参与有确认、有纪律的高胜率机会",
        },
        "NEUTRAL": {
            "posture_code": "PATIENT_OBSERVE",
            "posture_name": "耐心观察",
            "tone": "谨慎",
            "title": "亲爱的投资者，最新交易日水温中性，先等待方向自己走出来。",
            "wind": "市场风向仍在试探",
            "water": "资金在轮动中寻找下一步方向",
            "action": "不急着抢跑，耐心等更清晰的盘口与结构确认",
        },
        "RISK_OFF": {
            "posture_code": "DEFENSIVE",
            "posture_name": "收缩防线",
            "tone": "保守",
            "title": "亲爱的投资者，最新交易日市场偏弱，当前仍以防守为先。",
            "wind": "偏弱风向暂未扭转",
            "water": "资金更偏向防守而不是扩张",
            "action": "先保护本金，等待水温真正回暖后再提升进攻强度",
        },
        "CRASH": {
            "posture_code": "HARD_DEFENSE",
            "posture_name": "严防死守",
            "tone": "恶劣",
            "title": "亲爱的投资者，最新交易日市场环境偏冷，当前不要与下行趋势硬碰硬。",
            "wind": "市场风向仍明显偏空",
            "water": "资金仍处在避险模式",
            "action": "继续防守，避免在高波动环境中频繁试错",
        },
    },
}


def compose_market_state(row: dict[str, Any] | None) -> dict[str, str]:
    data = dict(row or {})
    benchmark_regime = str(data.get("benchmark_regime", "") or "").strip().upper()
    premarket_regime = str(data.get("premarket_regime", "") or "").strip().upper()
    benchmark_slot = _normalize_benchmark_slot(benchmark_regime)
    premarket_slot = _normalize_premarket_slot(premarket_regime)
    strategy_key = "NEUTRAL" if benchmark_slot == "UNKNOWN" else benchmark_slot
    strategy = (
        MARKET_BANNER_MATRIX.get(premarket_slot, {}).get(strategy_key) or MARKET_BANNER_MATRIX["CAUTION"]["NEUTRAL"]
    )

    return {
        "benchmark_slot": benchmark_slot,
        "premarket_slot": premarket_slot,
        "market_posture_code": strategy["posture_code"],
        "market_posture_name": strategy["posture_name"],
        "wind_phrase": strategy["wind"],
        "water_phrase": strategy["water"],
        "action_phrase": strategy["action"],
        "banner_tone": strategy["tone"],
    }


def compose_market_banner(row: dict[str, Any] | None) -> dict[str, str]:
    data = dict(row or {})
    benchmark_regime = str(data.get("benchmark_regime", "") or "").strip().upper()
    premarket_regime = str(data.get("premarket_regime", "") or "").strip().upper()
    state = compose_market_state(data)
    title = (
        MARKET_BANNER_MATRIX.get(state["premarket_slot"], {}).get(state["benchmark_slot"], {}).get("title")
        or "亲爱的投资者，最新交易日请顺势而为，保持节奏。"
    )
    body = (
        "以上指标按各自最新可用时间更新。"
        f"{_benchmark_state_sentence(benchmark_regime)}，{_premarket_state_sentence(premarket_regime)}。"
        f"当前{state['wind_phrase']}，{state['water_phrase']}。"
        f"{state['action_phrase']}。"
        "交易的本质是顺势而为：乘风而上，顺水推舟。"
    )

    return {
        **state,
        "banner_title": title,
        "banner_message": body,
    }


def _deep_merge_source_jobs(base: Any, patch: Any) -> dict[str, Any]:
    left = dict(base or {}) if isinstance(base, dict) else {}
    right = dict(patch or {}) if isinstance(patch, dict) else {}
    merged = dict(left)
    for key, value in right.items():
        if isinstance(merged.get(key), dict) and isinstance(value, dict):
            merged[key] = {**merged[key], **value}
        else:
            merged[key] = value
    return merged


def _custom_banner_fields(row: dict[str, Any] | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for key in CUSTOM_BANNER_FIELDS:
        text = str((row or {}).get(key) or "").strip()
        if text:
            out[key] = text
    return out


def _is_non_empty(value: Any) -> bool:
    if value is None:
        return False
    return str(value).strip() != ""


def _pick_latest_with_fields(rows: list[dict[str, Any]], required_any: tuple[str, ...]) -> dict[str, Any] | None:
    for row in rows:
        if any(_is_non_empty(row.get(key)) for key in required_any):
            return row
    return None


def _copy_market_signal_fields(target: dict[str, Any], source: dict[str, Any] | None, fields: tuple[str, ...]) -> None:
    if not source:
        return
    for key in fields:
        target[key] = source.get(key)


def _latest_market_signal_rows(client: Client, limit: int = 120) -> list[dict[str, Any]]:
    resp = (
        client.table(TABLE_MARKET_SIGNAL_DAILY)
        .select("*")
        .order("trade_date", desc=True)
        .order("updated_at", desc=True)
        .limit(limit)
        .execute()
    )
    return [dict(row) for row in (resp.data or []) if isinstance(row, dict)]


def _merge_latest_market_signal_rows(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not rows:
        return None
    merged = dict(rows[0])
    _copy_market_signal_fields(
        merged,
        _pick_latest_with_fields(rows, ("benchmark_regime", "main_index_close", "main_index_ma50", "main_index_ma200")),
        BENCHMARK_MERGE_FIELDS,
    )
    _copy_market_signal_fields(
        merged,
        _pick_latest_with_fields(rows, ("premarket_regime", "premarket_reasons")),
        PREMARKET_MERGE_FIELDS,
    )
    _copy_market_signal_fields(
        merged,
        _pick_latest_with_fields(rows, ("a50_close", "a50_pct_chg", "a50_value_date")),
        A50_MERGE_FIELDS,
    )
    _copy_market_signal_fields(
        merged,
        _pick_latest_with_fields(rows, ("vix_close", "vix_pct_chg", "vix_value_date")),
        VIX_MERGE_FIELDS,
    )
    custom_banner = _custom_banner_fields(merged)
    merged.update(compose_market_banner(merged))
    merged.update(custom_banner)
    return merged


def _normalize_row_for_upsert(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    if "trade_date" in out:
        out["trade_date"] = _normalize_trade_date(out.get("trade_date"))
    for key in [
        "main_index_close",
        "main_index_ma50",
        "main_index_ma200",
        "main_index_recent3_cum_pct",
        "main_index_today_pct",
        "smallcap_close",
        "smallcap_recent3_cum_pct",
        "a50_close",
        "a50_pct_chg",
        "vix_close",
        "vix_pct_chg",
    ]:
        if key in out:
            out[key] = _safe_float(out.get(key))
    for key in ["a50_value_date", "vix_value_date"]:
        if key in out and out.get(key):
            out[key] = _normalize_trade_date(out.get(key))
    if "premarket_reasons" in out and out.get("premarket_reasons") is None:
        out["premarket_reasons"] = []
    if "source_jobs" in out and not isinstance(out.get("source_jobs"), dict):
        out["source_jobs"] = {}
    return out


def _load_market_signal_by_trade_date(client: Client, trade_date: str) -> dict[str, Any] | None:
    resp = client.table(TABLE_MARKET_SIGNAL_DAILY).select("*").eq("trade_date", trade_date).limit(1).execute()
    if not resp.data:
        return None
    return dict(resp.data[0])


def _iter_market_signal_clients(client: Client | None = None) -> list[Client]:
    clients: list[Client] = []
    if client is not None:
        clients.append(client)
        return clients
    try:
        clients.append(_get_supabase_read_client())
    except Exception:
        logger.debug("failed to create supabase read client", exc_info=True)
    return clients


_UPSERT_MAX_RETRIES = 3


def _build_merged_row(existing: dict[str, Any], trade_date_text: str, patch: dict[str, Any]) -> dict[str, Any]:
    merged = dict(existing)
    merged.update(_normalize_row_for_upsert(dict(patch or {})))
    merged["trade_date"] = trade_date_text
    merged["source_jobs"] = _deep_merge_source_jobs(
        existing.get("source_jobs"),
        patch.get("source_jobs") if isinstance(patch, dict) else None,
    )
    custom_banner = _custom_banner_fields(patch)
    merged.update(compose_market_banner(merged))
    merged.update(custom_banner)
    merged["updated_at"] = datetime.now(UTC).isoformat()
    return merged


def _write_merged_row(client: Client, merged: dict[str, Any]) -> None:
    try:
        client.table(TABLE_MARKET_SIGNAL_DAILY).upsert(
            _normalize_row_for_upsert(merged),
            on_conflict="trade_date",
        ).execute()
    except Exception:
        fallback = {k: v for k, v in merged.items() if k not in STRUCTURED_MARKET_SIGNAL_FIELDS}
        client.table(TABLE_MARKET_SIGNAL_DAILY).upsert(
            _normalize_row_for_upsert(fallback),
            on_conflict="trade_date",
        ).execute()


def _row_unchanged_since_read(client: Client, trade_date_text: str, expected_updated_at: Any) -> bool:
    """Best-effort optimistic-lock check: re-read the row right before writing and bail out
    (to retry with a fresh snapshot) if another writer already updated it concurrently."""
    latest = _load_market_signal_by_trade_date(client, trade_date_text)
    if latest is None:
        return expected_updated_at is None
    return latest.get("updated_at") == expected_updated_at


def upsert_market_signal_daily(trade_date: date | str, patch: dict[str, Any]) -> bool:
    if not is_supabase_admin_configured():
        return False
    require_server_write_context("upsert market_signal_daily")
    trade_date_text = _normalize_trade_date(trade_date)
    try:
        client = _get_supabase_admin_client()
        for attempt in range(_UPSERT_MAX_RETRIES):
            existing = _load_market_signal_by_trade_date(client, trade_date_text) or {}
            merged = _build_merged_row(existing, trade_date_text, patch)
            if _row_unchanged_since_read(client, trade_date_text, existing.get("updated_at")):
                _write_merged_row(client, merged)
                return True
            logger.debug(
                "[supabase_market_signal] concurrent update detected for %s, retrying (%d/%d)",
                trade_date_text,
                attempt + 1,
                _UPSERT_MAX_RETRIES,
            )
        # Retries exhausted: write anyway so the job's own data isn't silently dropped, but a
        # concurrent writer may have raced us between the last check and this final write.
        existing = _load_market_signal_by_trade_date(client, trade_date_text) or {}
        _write_merged_row(client, _build_merged_row(existing, trade_date_text, patch))
        return True
    except Exception as e:
        logger.warning("[supabase_market_signal] upsert_market_signal_daily failed: %s", e)
        return False


def load_market_signal_daily(trade_date: date | str, client: Client | None = None) -> dict[str, Any] | None:
    trade_date_text = _normalize_trade_date(trade_date)
    for sb in _iter_market_signal_clients(client):
        try:
            row = _load_market_signal_by_trade_date(sb, trade_date_text)
            if row:
                return row
        except Exception as e:
            logger.debug("[supabase_market_signal] load_market_signal_daily failed for client: %s", e)
            continue
    return None


def load_latest_market_signal_daily(client: Client | None = None) -> dict[str, Any] | None:
    for sb in _iter_market_signal_clients(client):
        try:
            if sb is None:
                continue
            merged = _merge_latest_market_signal_rows(_latest_market_signal_rows(sb))
            if merged:
                return merged
        except Exception as e:
            logger.debug("[supabase_market_signal] load_latest_market_signal_daily failed for client: %s", e)
            continue
    return None
