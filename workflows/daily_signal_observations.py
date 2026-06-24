"""Signal-observation helpers for the daily funnel workflow."""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

LogFn = Callable[[str, str | None], None]


def apply_step3_springboard_updates(payload: list[dict], updates: dict[str, dict]) -> None:
    if not payload or not updates:
        return
    for row in payload:
        code = _last_six_digits(row.get("code", ""))
        if code in updates:
            row.update(updates[code])


def shadow_observation_inputs(step2_details: dict) -> tuple[dict[str, list[tuple[str, float]]], dict[str, str], dict]:
    score_map = step2_details.get("shadow_score_map") or {}
    triggers: dict[str, list[tuple[str, float]]] = {}
    source_map: dict[str, str] = {}
    for signal_type, source_key in (("shadow_added", "shadow_added"), ("shadow_removed", "shadow_removed")):
        rows: list[tuple[str, float]] = []
        for code in step2_details.get(signal_type, []) or []:
            code_s = str(code).strip()
            if code_s:
                rows.append((code_s, float(score_map.get(code_s, 0.0) or 0.0)))
                source_map[code_s] = source_key
        if rows:
            triggers[signal_type] = rows
    return triggers, source_map, score_map


def build_intraday_tail_map(
    step2_details: dict,
    ai_codes: list[str],
    logs_path: str | None,
    *,
    log_fn: LogFn | None = None,
) -> dict[str, dict]:
    if os.getenv("FUNNEL_INTRADAY_TAIL_CONFIRMATION", "1").strip().lower() in {"0", "false", "no", "off"}:
        return {}
    api_key = os.getenv("TICKFLOW_API_KEY", "").strip()
    if not api_key:
        _log(log_fn, "尾盘分钟线确认: 跳过（TICKFLOW_API_KEY 未配置）", logs_path)
        return {}
    items = _tail_confirmation_trigger_items(step2_details, ai_codes)
    if not items:
        return {}
    max_symbols = _env_int("FUNNEL_TAIL_CONFIRMATION_MAX_SYMBOLS", 40, minimum=1)
    codes = list(dict.fromkeys(code for _sig, code, _score in items))[:max_symbols]
    try:
        out = _fetch_intraday_tail_payloads(api_key, codes, items, step2_details)
        feature_count = sum(1 for key in out if ":" in key)
        _log(log_fn, f"尾盘分钟线确认: requested={len(codes)}, features={feature_count}", logs_path)
        return out
    except Exception as exc:
        _log(log_fn, f"尾盘分钟线确认失败（已降级）: {exc}", logs_path)
        return {}


def build_external_capital_context_map(
    step2_details: dict,
    ai_codes: list[str],
    logs_path: str | None,
    *,
    trade_date: str,
    log_fn: LogFn | None = None,
) -> dict[str, dict]:
    if os.getenv("FUNNEL_EXTERNAL_CAPITAL_CONTEXT", "1").strip().lower() in {"0", "false", "no", "off"}:
        return {}
    codes = _external_capital_codes(step2_details, ai_codes)
    if not codes:
        return {}
    max_symbols = _env_int("FUNNEL_EXTERNAL_CAPITAL_MAX_SYMBOLS", 20, minimum=1)
    include_tick = _env_flag("FUNNEL_EXTERNAL_CAPITAL_TICK_CONTEXT")
    tick_max = _env_int("FUNNEL_EXTERNAL_CAPITAL_TICK_MAX_SYMBOLS", 3, minimum=0)
    tick_min = _env_float("FUNNEL_EXTERNAL_CAPITAL_TICK_MIN_AMOUNT_YUAN", 1_000_000.0)
    try:
        from integrations.external_capital_context import build_external_capital_context

        requested = codes[:max_symbols]
        out = build_external_capital_context(
            requested,
            trade_date,
            include_tick=include_tick,
            tick_max_symbols=tick_max,
            tick_min_amount_yuan=tick_min,
        )
        _log(
            log_fn,
            f"外部资金佐证: requested={len(requested)}, features={len(out)}, tick={'on' if include_tick else 'off'}",
            logs_path,
        )
        return out
    except Exception as exc:
        _log(log_fn, f"外部资金佐证失败（已降级）: {exc}", logs_path)
        return {}


def build_signal_observation_rows(
    step2_details: dict, regime: str, ai_codes: list[str], *, trade_date: str
) -> list[dict]:
    from core.signal_feedback import build_signal_observations

    metrics, name_map, sector_map, stage_map, channel_map, close_map, springboard_map, footprint_map = (
        _observation_context(step2_details)
    )
    selected_for_ai = step2_details.get("selected_for_ai", []) or []
    return build_signal_observations(
        trade_date,
        step2_details.get("review_triggers") or step2_details.get("triggers") or {},
        regime=regime,
        selected_for_ai=selected_for_ai,
        ai_recommended=ai_codes,
        name_map=name_map,
        sector_map=sector_map,
        score_map=step2_details.get("priority_score_map", {}) or {},
        stage_map=stage_map,
        channel_map=channel_map,
        latest_close_map=close_map,
        source_map=_signal_observation_source_map(step2_details),
        springboard_map=springboard_map,
        footprint_map=footprint_map,
        intraday_tail_map=step2_details.get("intraday_tail_map") or {},
        source_context_map=step2_details.get("source_context_map") or {},
        selection_mode=os.getenv("FUNNEL_AI_SELECTION_MODE", "quota"),
        policy_version=f"dynamic:{os.getenv('FUNNEL_DYNAMIC_POLICY', 'off')}",
        rank_map={str(code): idx + 1 for idx, code in enumerate(selected_for_ai)},
    )


def build_shadow_observation_rows(step2_details: dict, regime: str, *, trade_date: str) -> list[dict]:
    from core.signal_feedback import build_signal_observations

    shadow_triggers, shadow_source_map, shadow_score_map = shadow_observation_inputs(step2_details)
    if not shadow_triggers:
        return []
    _, name_map, sector_map, stage_map, channel_map, close_map, _, footprint_map = _observation_context(step2_details)
    return build_signal_observations(
        trade_date,
        shadow_triggers,
        regime=regime,
        name_map=name_map,
        sector_map=sector_map,
        score_map=shadow_score_map,
        stage_map=stage_map,
        channel_map=channel_map,
        latest_close_map=close_map,
        source_map=shadow_source_map,
        footprint_map=footprint_map,
        intraday_tail_map=step2_details.get("intraday_tail_map") or {},
        source_context_map=step2_details.get("source_context_map") or {},
        selection_mode="shadow",
        policy_version=f"dynamic:{os.getenv('FUNNEL_DYNAMIC_POLICY', 'off')}",
    )


def build_external_seed_signal_rows(step2_details: dict, regime: str, *, trade_date: str) -> list[dict]:
    from core.signal_feedback import build_signal_observations

    metrics, name_map, sector_map, stage_map, channel_map, close_map, springboard_map, footprint_map = (
        _observation_context(step2_details)
    )
    selected = {str(code).strip() for code in step2_details.get("selected_for_ai", []) if str(code).strip()}
    triggers = {
        signal_type: [(code, score) for code, score in hits if str(code).strip() not in selected]
        for signal_type, hits in (metrics.get("external_seed_l4_triggers") or {}).items()
    }
    triggers = {signal_type: hits for signal_type, hits in triggers.items() if hits}
    if not triggers:
        return []
    source = f"external_seed:{metrics.get('external_seed_source') or 'external'}"
    source_map = {str(code): source for hits in triggers.values() for code, _score in hits}
    return build_signal_observations(
        trade_date,
        triggers,
        regime=regime,
        name_map=name_map,
        sector_map=sector_map,
        score_map=step2_details.get("priority_score_map", {}) or {},
        stage_map=stage_map,
        channel_map=channel_map,
        latest_close_map=close_map,
        source_map=source_map,
        springboard_map=springboard_map,
        footprint_map=footprint_map,
        intraday_tail_map=step2_details.get("intraday_tail_map") or {},
        source_context_map=step2_details.get("source_context_map") or {},
        selection_mode="external_seed_shadow",
        policy_version=f"external_seed:{metrics.get('external_seed_source') or 'external'}",
    )


def persist_external_seed_observations(
    step2_details: dict,
    logs_path: str | None,
    *,
    dry_run: bool = False,
    log_fn: LogFn | None = None,
) -> None:
    rows = (step2_details.get("metrics", {}) or {}).get("external_seed_observation_rows") or []
    if not rows:
        return
    if dry_run:
        _log(log_fn, f"预演模式: 跳过外部观察入库 rows={len(rows)}", logs_path)
        return
    try:
        from integrations.supabase_external_seeds import upsert_external_seed_observations

        written = upsert_external_seed_observations(rows)
        _log(log_fn, f"外部观察入库: rows={len(rows)}, written={written}", logs_path)
    except Exception as exc:
        _log(log_fn, f"外部观察入库失败（已降级）: {exc}", logs_path)


def persist_signal_observations(
    step2_details: dict,
    benchmark_context: dict,
    ai_codes: list[str],
    logs_path: str | None,
    *,
    trade_date: str,
    dry_run: bool = False,
    log_fn: LogFn | None = None,
) -> bool:
    if not step2_details:
        return True
    if dry_run:
        _log(log_fn, "预演模式: 跳过信号观察样本入库", logs_path)
        return True
    try:
        from integrations.supabase_signal_feedback import upsert_signal_observations

        regime = str((benchmark_context or {}).get("regime") or "NEUTRAL")
        if "intraday_tail_map" not in step2_details:
            step2_details["intraday_tail_map"] = build_intraday_tail_map(
                step2_details, ai_codes, logs_path, log_fn=log_fn
            )
        if "source_context_map" not in step2_details:
            step2_details["source_context_map"] = build_external_capital_context_map(
                step2_details,
                ai_codes,
                logs_path,
                trade_date=trade_date,
                log_fn=log_fn,
            )
        rows = build_signal_observation_rows(step2_details, regime, ai_codes, trade_date=trade_date)
        rows.extend(build_shadow_observation_rows(step2_details, regime, trade_date=trade_date))
        rows.extend(build_external_seed_signal_rows(step2_details, regime, trade_date=trade_date))
        written = upsert_signal_observations(rows)
        _log(log_fn, f"信号观察样本入库: rows={len(rows)}, written={written}", logs_path)
        return True
    except Exception as exc:
        _log(log_fn, f"信号观察样本入库失败: {exc}", logs_path)
        return False


def empty_springboard_fields() -> dict:
    return {
        "springboard_a": False,
        "springboard_b": False,
        "springboard_c": False,
        "springboard_grade": "none",
        "springboard_met_count": 0,
        "springboard_support": None,
        "springboard_touch_count": 0,
        "springboard_evidence": {},
        "springboard_scored": False,
    }


def build_springboard_map(step2_details: dict) -> dict[str, dict]:
    from core.signal_confirmation import score_springboard_abc

    all_df_map = step2_details.get("all_df_map", {})
    triggers = step2_details.get("review_triggers") or step2_details.get("triggers", {})
    out: dict[str, dict] = {}
    for sig_type, hits in triggers.items():
        for code, _score in hits:
            code_s = str(code).strip()
            sig_s = str(sig_type).strip().lower()
            if not code_s or not sig_s:
                continue
            key = f"{sig_s}:{code_s}"
            df = all_df_map.get(code_s)
            out[key] = (
                empty_springboard_fields()
                if df is None or df.empty
                else _springboard_fields(score_springboard_abc(df, sig_s))
            )
            out.setdefault(code_s, out[key])
    return out


def _fetch_intraday_tail_payloads(
    api_key: str,
    codes: list[str],
    items: list[tuple[str, str, float]],
    step2_details: dict,
) -> dict[str, dict]:
    from integrations.tickflow_client import TickFlowClient, normalize_cn_symbol

    symbols = [normalize_cn_symbol(code) for code in codes]
    data_map = TickFlowClient(api_key=api_key).get_intraday_batch(symbols, period="1m", count=5000)
    springboard_map = step2_details.get("springboard_map") or build_springboard_map(step2_details)
    allowed = set(codes)
    out: dict[str, dict[str, Any]] = {}
    for sig, code, trigger_score in items:
        if code not in allowed:
            continue
        df_1m = data_map.get(normalize_cn_symbol(code))
        if df_1m is None or df_1m.empty:
            continue
        springboard = springboard_map.get(f"{sig}:{code}") or springboard_map.get(code) or {}
        support = springboard.get("springboard_support")
        payload = _intraday_tail_payload(
            df_1m,
            signal_type=sig,
            trigger_score=trigger_score,
            daily_context={"support_level": support} if support else None,
        )
        out[f"{sig}:{code}"] = payload
        out.setdefault(code, payload)
    return out


def _intraday_tail_payload(
    df_1m: Any,
    *,
    signal_type: str,
    trigger_score: float,
    daily_context: dict | None,
) -> dict:
    from core.tail_buy.strategy import compute_tail_features, score_tail_features

    features = compute_tail_features(df_1m, daily_context=daily_context)
    tail_score, tail_decision, reasons = score_tail_features(
        features,
        signal_score=trigger_score,
        signal_type=signal_type,
        status="pending",
    )
    return {
        "version": "intraday_tail_confirmation_v1",
        "source": "tickflow_1m",
        "tail_score": round(float(tail_score), 1),
        "tail_decision": tail_decision,
        "tail_reasons": reasons[:6],
        **features,
    }


def _tail_confirmation_trigger_items(step2_details: dict, ai_codes: list[str]) -> list[tuple[str, str, float]]:
    target_order: list[str] = []
    for raw in list(step2_details.get("selected_for_ai", []) or []) + list(ai_codes or []):
        code = str(raw or "").strip()
        if code and code not in target_order:
            target_order.append(code)
    if not target_order:
        return []
    items: list[tuple[str, str, float]] = []
    for signal_type, hits in (step2_details.get("review_triggers") or step2_details.get("triggers") or {}).items():
        sig = str(signal_type or "").strip().lower()
        if not sig:
            continue
        items.extend(
            (sig, code, _safe_float(score)) for code, score in hits or [] if str(code or "").strip() in target_order
        )
    return items


def _external_capital_codes(step2_details: dict, ai_codes: list[str]) -> list[str]:
    ordered: list[str] = []
    for raw in list(step2_details.get("selected_for_ai", []) or []) + list(ai_codes or []):
        code = str(raw or "").strip()
        if code and code not in ordered:
            ordered.append(code)
    if ordered:
        return ordered
    return list(dict.fromkeys(code for _sig, code, _score in _tail_confirmation_trigger_items(step2_details, ai_codes)))


def _observation_context(step2_details: dict) -> tuple[dict, dict, dict, dict, dict, dict, dict, dict]:
    metrics = step2_details.get("metrics", {}) or {}
    footprint_map = step2_details.get("footprint_map")
    if footprint_map is None:
        footprint_map = _build_footprint_map(step2_details)
        step2_details["footprint_map"] = footprint_map
    return (
        metrics,
        step2_details.get("name_map", {}) or {},
        step2_details.get("sector_map", {}) or {},
        metrics.get("accum_stage_map", {}) or {},
        metrics.get("layer2_channel_map", {}) or {},
        metrics.get("latest_close_map", {}) or {},
        step2_details.get("springboard_map") or build_springboard_map(step2_details),
        footprint_map,
    )


def _build_footprint_map(step2_details: dict) -> dict[str, dict]:
    from core.price_action_footprint import build_price_action_footprint_map

    metrics = step2_details.get("metrics", {}) or {}
    df_map = step2_details.get("all_df_map") or metrics.get("all_df_map") or {}
    return build_price_action_footprint_map(_merge_observation_trigger_maps(step2_details), df_map)


def _merge_observation_trigger_maps(step2_details: dict) -> dict[str, list[tuple[str, float]]]:
    metrics = step2_details.get("metrics", {}) or {}
    out: dict[str, list[tuple[str, float]]] = {}
    for trigger_map in (
        step2_details.get("review_triggers") or step2_details.get("triggers") or {},
        metrics.get("external_seed_l4_triggers") or {},
    ):
        for signal_type, hits in trigger_map.items():
            out.setdefault(str(signal_type).strip().lower(), []).extend(hits or [])
    return {signal_type: hits for signal_type, hits in out.items() if signal_type and hits}


def _signal_observation_source_map(step2_details: dict) -> dict[str, str]:
    metrics = step2_details.get("metrics", {}) or {}
    bypass_codes = {str(c).strip() for c in step2_details.get("l2_bypass_selected", []) if str(c).strip()}
    strategic_codes = {str(c).strip() for c in step2_details.get("strategic_l2_bypass_selected", []) if str(c).strip()}
    external_codes = {str(c).strip() for c in step2_details.get("external_seed_selected", []) if str(c).strip()}
    source_map = {code: "l2_bypass" for code in bypass_codes}
    source_map.update({code: "strategic_l2_bypass" for code in strategic_codes})
    source_map.update(
        {code: f"external_seed:{metrics.get('external_seed_source') or 'external'}" for code in external_codes}
    )
    return source_map


def _springboard_fields(result: dict) -> dict:
    return {
        "springboard_a": bool(result.get("a")),
        "springboard_b": bool(result.get("b")),
        "springboard_c": bool(result.get("c")),
        "springboard_grade": str(result.get("grade") or "none"),
        "springboard_met_count": int(result.get("met_count") or 0),
        "springboard_support": result.get("support"),
        "springboard_touch_count": int(result.get("touch_count") or 0),
        "springboard_evidence": result.get("evidence") or {},
        "springboard_scored": True,
    }


def _last_six_digits(value: object) -> str:
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    return digits[-6:].zfill(6) if digits else ""


def _safe_float(value: object) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _env_flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, *, minimum: int) -> int:
    try:
        return max(int(os.getenv(name, str(default))), minimum)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _log(log_fn: LogFn | None, message: str, logs_path: str | None) -> None:
    if log_fn is not None:
        log_fn(message, logs_path)
