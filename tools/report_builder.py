"""
AI 研报 prompt 构建 + 报告解析工具。

供 step3_batch_report 和 step4_rebalancer 使用的报告构建、解析与分流逻辑。
"""

from __future__ import annotations

import pandas as pd

from utils.safe import safe_float as _safe_float_or_default


def _safe_float(value: object) -> float | None:
    return _safe_float_or_default(value, None)


# ── 环境变量配置 ──

RECENT_DAYS = 15
HIGHLIGHT_DAYS = 60
HIGHLIGHT_PCT_THRESHOLD = 5.0
HIGHLIGHT_VOL_RATIO = 2.0
SUPPLY_HEAVY_VOL_RATIO = 1.5
SUPPLY_DRY_VOL_RATIO = 0.8
SUPPLY_TEST_MAX_ABS_PCT = 1.0
KEY_LEVEL_WINDOW = 20
_SIGNAL_TAG_MAP = [
    ("sos", "向上突破异动"),
    ("spring", "假跌破回收异动"),
    ("lps", "缩量回踩企稳异动"),
    ("evr", "放量滞涨背离异动"),
    ("compression", "窄幅缩量蓄势异动"),
]
_SPRINGBOARD_RULE_MAP = {
    "A": "A=缩量高收测试",
    "B": "B=放量高收突破",
    "C": "C=支撑多次测试",
}
# ── Payload 构建工具 ──


def _format_slice_date(value: object) -> str:
    s = str(value or "")
    return s[5:10] if len(s) >= 10 else s


def _build_supply_demand_summary(df: pd.DataFrame) -> str:
    """构建供求摘要文本。"""
    df_s = df.copy().sort_values("date").reset_index(drop=True)
    if df_s.empty:
        return ""

    close = pd.to_numeric(df_s.get("close"), errors="coerce")
    volume = pd.to_numeric(df_s.get("volume"), errors="coerce")
    vol_ma20 = volume.rolling(20).mean()
    df_s["pct_chg_calc"] = close.pct_change() * 100
    df_s["vol_ratio"] = volume / vol_ma20.replace(0, pd.NA)
    recent = df_s.tail(RECENT_DAYS).copy()

    pct = pd.to_numeric(recent.get("pct_chg_calc"), errors="coerce")
    vol_ratio = pd.to_numeric(recent.get("vol_ratio"), errors="coerce")
    down_heavy = recent[(pct < 0) & (vol_ratio >= SUPPLY_HEAVY_VOL_RATIO)]
    dry_pullback = recent[(pct < 0) & (vol_ratio <= SUPPLY_DRY_VOL_RATIO)]
    quiet_tests = recent[(pct.abs() <= SUPPLY_TEST_MAX_ABS_PCT) & (vol_ratio <= SUPPLY_DRY_VOL_RATIO)]
    breakout_days = recent[(pct >= HIGHLIGHT_PCT_THRESHOLD) & (vol_ratio >= HIGHLIGHT_VOL_RATIO)]

    key_window = min(max(KEY_LEVEL_WINDOW, 5), len(df_s))
    key_zone = df_s.tail(key_window)
    key_high = pd.to_numeric(key_zone.get("high"), errors="coerce").dropna()
    key_low = pd.to_numeric(key_zone.get("low"), errors="coerce").dropna()
    zone_text = ""
    if not key_high.empty and not key_low.empty:
        zone_text = f"，近{key_window}日区间=[{float(key_low.min()):.2f}, {float(key_high.max()):.2f}]"

    extra_tags: list[str] = []
    if not breakout_days.empty:
        extra_tags.append(f"最近爆量上攻={_format_slice_date(breakout_days.iloc[-1].get('date'))}")
    if not down_heavy.empty:
        extra_tags.append(f"最近供应放大={_format_slice_date(down_heavy.iloc[-1].get('date'))}")
    if not quiet_tests.empty:
        extra_tags.append(f"最近低量测试={_format_slice_date(quiet_tests.iloc[-1].get('date'))}")

    summary = (
        f"  [供求摘要] 近{RECENT_DAYS}日下跌放量{len(down_heavy)}次，"
        f"缩量回踩{len(dry_pullback)}次，低量测试{len(quiet_tests)}次"
        f"{zone_text}"
    )
    if extra_tags:
        summary += "，" + "，".join(extra_tags)
    return summary + "\n"


def _springboard_codes(grade: str | None) -> list[str]:
    raw = str(grade or "").strip().upper()
    if not raw or raw == "NONE":
        return []
    parts = {part.strip() for part in raw.split("+")}
    return [code for code in ("A", "B", "C") if code in parts]


def _springboard_grade_text(grade: str | None) -> str:
    raw = str(grade or "").strip()
    if not raw:
        return ""
    if raw.lower() == "none":
        return "none（0/3，无硬门槛）"
    codes = _springboard_codes(raw)
    labels = [_SPRINGBOARD_RULE_MAP.get(code, code) for code in codes]
    return f"{raw}（{' + '.join(labels)}）" if labels else raw


def _build_trading_range_line(df: pd.DataFrame, close_val: float) -> str:
    if df.empty:
        return ""
    base = df.tail(KEY_LEVEL_WINDOW + 1).iloc[:-1] if len(df) > KEY_LEVEL_WINDOW else df.tail(KEY_LEVEL_WINDOW)
    highs = pd.to_numeric(base.get("high"), errors="coerce").dropna()
    lows = pd.to_numeric(base.get("low"), errors="coerce").dropna()
    if highs.empty or lows.empty:
        return ""
    creek = float(highs.max())
    ice = float(lows.min())
    width = creek - ice
    pos = None if width <= 0 else max(0.0, min(100.0, (float(close_val) - ice) / width * 100))
    pos_text = "NA" if pos is None else f"{pos:.0f}%"
    return f"  [结构支撑/阻力] Creek(箱体上沿):{creek:.2f}, Ice(箱体下沿):{ice:.2f}, 区间位置:{pos_text}\n"


def _format_financial_snapshot(financial_metrics: dict | None) -> str:
    if not financial_metrics:
        return ""
    pct_keys = {"roe", "net_income_yoy", "gross_margin", "debt_to_asset_ratio"}
    parts = []
    for key, label in [
        ("eps_basic", "EPS"),
        ("roe", "ROE"),
        ("net_income_yoy", "净利润同比"),
        ("gross_margin", "毛利率"),
        ("debt_to_asset_ratio", "资产负债率"),
    ]:
        value = _safe_float(financial_metrics.get(key))
        if value is not None:
            parts.append(f"{label}: {value:.1f}%" if key in pct_keys else f"{label}: {value:.2f}")
    return f"  [基本面快照] {' | '.join(parts)}\n" if parts else ""


def _build_candidate_type_line(
    raw_tag: str,
    facts: list[str],
    springboard_grade: str | None,
    exit_signal: str | None,
    sector_state_code: str | None,
) -> str:
    raw_lower = str(raw_tag or "").lower()
    if exit_signal:
        kind = "冲突复核（退出预警 + 初筛异动）"
    elif str(sector_state_code or "").upper() == "CONSENSUS_CLIMAX":
        kind = "高潮风险复核"
    elif len(_springboard_codes(springboard_grade)) >= 2:
        kind = "起跳板复核"
    elif "sos" in raw_lower:
        kind = "强突破复核"
    elif any(token in raw_lower for token in ("spring", "lps", "evr")):
        kind = "左侧吸筹复核"
    else:
        kind = "结构候选复核"
    source = "/".join(facts) if facts else (str(raw_tag or "").strip() or "未标注")
    return f"  [候选类型] {kind} | 信号来源:{source}\n"


def _build_conflict_line(exit_signal: str | None) -> str:
    if not exit_signal:
        return ""
    return (
        "  [冲突提示] 同时存在退出预警与初筛异动，默认按诱多/修复失败审查；只有重新站回关键位且放量高收才允许升级。\n"
    )


def _row_vsa_tags(row: pd.Series, vol_ratio: float) -> list[str]:
    pct = _safe_float(row.get("pct_chg_calc")) or 0.0
    amp = _safe_float(row.get("amplitude_pct")) or 0.0
    close_pos = _safe_float(row.get("close_pos_pct")) or 50.0
    open_v = _safe_float(row.get("open"))
    close_v = _safe_float(row.get("close"))
    low_v = _safe_float(row.get("low"))
    high_v = _safe_float(row.get("high"))
    tags: list[str] = []
    if amp >= 5 and close_pos >= 80 and vol_ratio >= 1.5:
        tags.append("宽幅高收放量")
    if amp >= 5 and close_pos <= 25 and vol_ratio >= 1.5:
        tags.append("宽幅低收放量")
    if None not in (open_v, close_v, low_v, high_v) and high_v > low_v:
        lower_shadow = (min(open_v, close_v) - low_v) / (high_v - low_v) * 100
        if lower_shadow >= 40 and close_pos >= 65:
            tags.append("长下影收复")
    if vol_ratio < 0.8 and close_pos >= 60 and abs(pct) <= 2.5:
        tags.append("缩量高收测试")
    if pct < 0 and vol_ratio >= 1.5 and close_pos <= 50:
        tags.append("供应放大")
    if pct >= HIGHLIGHT_PCT_THRESHOLD and vol_ratio >= HIGHLIGHT_VOL_RATIO and close_pos >= 70:
        tags.append("放量突破")
    return tags[:3]


def _build_recent_slice(df: pd.DataFrame) -> str:
    recent_lines = ["  [近15日量价切片]:"]
    for _, row in df.tail(RECENT_DAYS).iterrows():
        vol_ma20 = _safe_float(row.get("vol_ma20"))
        volume = _safe_float(row.get("volume")) or 0.0
        vol_ratio = volume / vol_ma20 if vol_ma20 and vol_ma20 > 0 else 0.0
        pct = _safe_float(row.get("pct_chg_calc")) or 0.0
        amp = _safe_float(row.get("amplitude_pct"))
        close_pos = _safe_float(row.get("close_pos_pct"))
        tags = _row_vsa_tags(row, vol_ratio)
        date_str = str(row.get("date", ""))[5:10]
        tag_text = f" [{'/'.join(tags)}]" if tags else ""
        amp_text = f"{amp:.1f}%" if amp is not None else "NA"
        close_pos_text = f"{close_pos:.0f}%" if close_pos is not None else "NA"
        recent_lines.append(
            f"    {date_str}: 收{float(row['close']):.2f} ({pct:+.1f}%), "
            f"振幅:{amp_text}, 收位:{close_pos_text}, 量比:{vol_ratio:.1f}x{tag_text}"
        )
    return "\n".join(recent_lines) + "\n"


def _build_highlight_section(df: pd.DataFrame) -> str:
    highlights = []
    for _, row in df.tail(HIGHLIGHT_DAYS).iterrows():
        pct = _safe_float(row.get("pct_chg_calc")) or 0.0
        vol_ma20 = _safe_float(row.get("vol_ma20"))
        volume = _safe_float(row.get("volume")) or 0.0
        vol_ratio = volume / vol_ma20 if vol_ma20 and vol_ma20 > 0 else 0.0
        if abs(pct) < HIGHLIGHT_PCT_THRESHOLD and vol_ratio < HIGHLIGHT_VOL_RATIO:
            continue
        tag_parts = []
        if abs(pct) >= HIGHLIGHT_PCT_THRESHOLD:
            tag_parts.append(f"涨跌{pct:+.1f}%")
        if vol_ratio >= HIGHLIGHT_VOL_RATIO:
            tag_parts.append(f"量比{vol_ratio:.1f}x")
        date_str = str(row.get("date", ""))[5:10]
        highlights.append(f"    {date_str}: 收{float(row['close']):.2f} ({', '.join(tag_parts)})")
    return "\n  [近60日异动高光]:\n" + "\n".join(highlights) + "\n" if highlights else ""


def _build_confirmation_gate_line(
    candidate_source: str | None,
    signal_status: str | None,
    confirm_date: str | None,
    confirm_reason: str | None,
) -> str:
    source = str(candidate_source or "").strip() or "未标注"
    status = str(signal_status or "").strip().lower()
    confirmed = status == "confirmed" or "二次确认" in source
    status_text = "confirmed" if confirmed else "unconfirmed"
    parts = [f"来源:{source}", f"二次确认:{status_text}"]
    if confirm_date:
        parts.append(f"确认日:{str(confirm_date).strip()}")
    if confirm_reason:
        parts.append(f"确认理由:{str(confirm_reason).strip()}")
    return f"  [交易闸门] {' | '.join(parts)}\n"


def _prepare_payload_frame(df: pd.DataFrame) -> pd.DataFrame:
    frame = df.copy().sort_values("date").reset_index(drop=True)
    close = frame["close"].astype(float)
    high = frame["high"].astype(float)
    low = frame["low"].astype(float)
    volume = frame["volume"].astype(float)
    amount = (
        pd.to_numeric(frame["amount"], errors="coerce")
        if "amount" in frame.columns
        else pd.Series(close * volume, index=frame.index, dtype=float)
    )
    if amount.isna().all():
        amount = pd.Series(close * volume, index=frame.index, dtype=float)
    frame["ma50"] = close.rolling(50).mean()
    frame["ma200"] = close.rolling(200).mean()
    frame["vol_ma20"] = volume.rolling(20).mean()
    frame["amount_ma20"] = amount.rolling(20).mean()
    frame["pct_chg_calc"] = close.pct_change() * 100
    prev_close = close.shift(1)
    amplitude_base = prev_close.where(prev_close > 0, close.where(close > 0, pd.NA))
    frame["amplitude_pct"] = ((high - low) / amplitude_base.replace(0, pd.NA) * 100).astype(float)
    span = (high - low).replace(0, float("nan"))
    close_pos = ((close - low) / span * 100).clip(lower=0, upper=100)
    frame["close_pos_pct"] = pd.to_numeric(close_pos, errors="coerce").fillna(50.0).astype(float)
    return frame


def _build_structure_background(
    df: pd.DataFrame,
    market_cap_yi: float | None,
    avg_amount_20_yi: float | None,
) -> tuple[str, float]:
    latest = df.iloc[-1]
    ma50_val = latest["ma50"]
    ma200_val = latest["ma200"]
    close_val = latest["close"]
    amount_ma20_val = latest.get("amount_ma20", pd.NA)
    market_cap_val = pd.to_numeric(market_cap_yi, errors="coerce")
    avg_amount_val = pd.to_numeric(avg_amount_20_yi, errors="coerce")
    if pd.isna(avg_amount_val):
        avg_amount_val = amount_ma20_val / 1e8 if pd.notna(amount_ma20_val) else pd.NA

    extra_parts: list[str] = []
    if pd.notna(ma50_val):
        extra_parts.append(f"MA50:{ma50_val:.2f}")
    if pd.notna(ma200_val):
        extra_parts.append(f"MA200:{ma200_val:.2f}")
    if pd.notna(ma200_val) and ma200_val > 0:
        bias_200 = (close_val - ma200_val) / ma200_val * 100
        extra_parts.append(f"年线乖离:{bias_200:.1f}%")
    if pd.notna(market_cap_val):
        extra_parts.append(f"市值:{float(market_cap_val):.0f}亿")
    if pd.notna(avg_amount_val):
        extra_parts.append(f"20日均成交:{float(avg_amount_val):.2f}亿")

    extra_text = ", ".join(extra_parts)
    if extra_text:
        return f"  [结构背景] 现价:{close_val:.2f}, {extra_text}", close_val
    return f"  [结构背景] 现价:{close_val:.2f}", close_val


def _signal_context(wyckoff_tag: str) -> tuple[str, list[str], str]:
    raw_tag = str(wyckoff_tag or "").strip()
    if not raw_tag:
        return "", [], ""
    lowered = raw_tag.lower()
    facts = [label for token, label in _SIGNAL_TAG_MAP if token in lowered]
    tag_text = f" | 量化初筛假设：{'/'.join(facts)}" if facts else f" | 量化初筛假设：{raw_tag}"
    return raw_tag, facts, tag_text


def _build_sector_state_line(sector_state: str | None, sector_state_code: str | None) -> str:
    if not sector_state:
        return ""
    state_text = str(sector_state).strip()
    state_code_text = str(sector_state_code or "").strip()
    if state_code_text:
        state_text = f"{state_text} ({state_code_text})"
    return f"  [板块状态] {state_text}\n"


def _build_exit_warning_line(
    exit_signal: str | None,
    exit_price: float | None,
    exit_reason: str | None,
) -> str:
    if not exit_signal:
        return ""
    exit_parts = [f"信号: {exit_signal}"]
    if exit_price is not None:
        exit_parts.append(f"触发价: {exit_price:.2f}")
    if exit_reason:
        exit_parts.append(f"原因: {exit_reason}")
    return f"  [退出预警] {', '.join(exit_parts)}\n"


def _build_springboard_line(springboard_grade: str | None) -> str:
    if not springboard_grade:
        return ""
    met = len(_springboard_codes(springboard_grade))
    grade_text = _springboard_grade_text(springboard_grade)
    return f"  [起跳板预判] 满足条件: {grade_text} ({met}/3)\n"


def _build_payload_header(
    *,
    stock_code: str,
    stock_name: str,
    policy_tag: str | None,
    tag_text: str,
    df: pd.DataFrame,
    close_val: float,
    background: str,
    raw_tag: str,
    facts: list[str],
    springboard_grade: str | None,
    exit_signal: str | None,
    sector_state_code: str | None,
    candidate_source: str | None,
    signal_status: str | None,
    confirm_date: str | None,
    confirm_reason: str | None,
    stage: str | None,
    industry: str | None,
    sector_state: str | None,
    sector_note: str | None,
    exit_price: float | None,
    exit_reason: str | None,
    financial_metrics: dict | None,
) -> str:
    policy_prefix = f" {policy_tag}" if policy_tag else ""
    header = f"\u2022 {stock_code} {stock_name}{policy_prefix}{tag_text}\n"
    header += f"  [价格锚点] 最新收盘价:{close_val:.2f}\n{background}\n"
    header += _build_trading_range_line(df, close_val)
    header += _build_candidate_type_line(raw_tag, facts, springboard_grade, exit_signal, sector_state_code)
    header += _build_confirmation_gate_line(candidate_source, signal_status, confirm_date, confirm_reason)
    if stage:
        header += f"  [阶段假设] {stage}\n"
    if industry:
        header += f"  [行业/主营] {industry}\n"
    header += _build_sector_state_line(sector_state, sector_state_code)
    if sector_note:
        header += f"  [板块证据] {str(sector_note).strip()}\n"
    header += _build_exit_warning_line(exit_signal, exit_price, exit_reason)
    header += _build_conflict_line(exit_signal)
    header += _format_financial_snapshot(financial_metrics)
    header += _build_springboard_line(springboard_grade)
    return header


def generate_stock_payload(
    stock_code: str,
    stock_name: str,
    wyckoff_tag: str,
    df: pd.DataFrame,
    *,
    industry: str | None = None,
    market_cap_yi: float | None = None,
    avg_amount_20_yi: float | None = None,
    quant_score: float | None = None,
    industry_rank: int | None = None,
    policy_tag: str | None = None,
    sector_state: str | None = None,
    sector_state_code: str | None = None,
    sector_note: str | None = None,
    track: str | None = None,
    stage: str | None = None,
    funnel_score: float | None = None,
    exit_signal: str | None = None,
    exit_price: float | None = None,
    exit_reason: str | None = None,
    financial_metrics: dict | None = None,
    springboard_grade: str | None = None,
    candidate_source: str | None = None,
    signal_status: str | None = None,
    confirm_date: str | None = None,
    confirm_reason: str | None = None,
) -> str:
    """
    将 320 个交易日 OHLCV 浓缩为发给 AI 的高密度文本。
    1. 大背景（MA50 / MA200 / 乖离率 / 市值 / 成交额）
    1.5 板块状态（轮动水温 + 证据）
    2. 近 15 日量价切片（放量比 + 涨跌幅 + 振幅 + 收盘位置）
    3. 近 60 日异动高光时刻
    """
    df = _prepare_payload_frame(df)
    background, close_val = _build_structure_background(df, market_cap_yi, avg_amount_20_yi)
    raw_tag, facts, tag_text = _signal_context(wyckoff_tag)
    header = _build_payload_header(
        stock_code=stock_code,
        stock_name=stock_name,
        policy_tag=policy_tag,
        tag_text=tag_text,
        df=df,
        close_val=close_val,
        background=background,
        raw_tag=raw_tag,
        facts=facts,
        springboard_grade=springboard_grade,
        exit_signal=exit_signal,
        sector_state_code=sector_state_code,
        candidate_source=candidate_source,
        signal_status=signal_status,
        confirm_date=confirm_date,
        confirm_reason=confirm_reason,
        stage=stage,
        industry=industry,
        sector_state=sector_state,
        sector_note=sector_note,
        exit_price=exit_price,
        exit_reason=exit_reason,
        financial_metrics=financial_metrics,
    )

    supply_summary = _build_supply_demand_summary(df)
    recent_section = _build_recent_slice(df)
    highlight_section = _build_highlight_section(df)
    return header + recent_section + supply_summary + highlight_section + "\n"
