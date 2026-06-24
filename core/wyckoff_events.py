"""Wyckoff signal-to-event classification.

This borrows CZSC's Signal -> Event mindset without importing Chan theory
objects.  Wyckoff remains the domain language; this module only turns raw
trigger facts into readable, testable event labels.
"""

from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class WyckoffEvent:
    event_id: str
    label: str
    track: str
    action: str
    confidence: str
    reasons: tuple[str, ...]
    watch_points: tuple[str, ...]


@dataclass(frozen=True)
class _EventSpec:
    event_id: str
    label: str
    track: str
    action: str
    confidence: str
    reasons: tuple[str, ...]
    watch_points: tuple[str, ...]


_RIGHT_SIDE_IGNITION = _EventSpec(
    event_id="right_side_ignition",
    label="右侧点火",
    track="Trend",
    action="强度观察",
    confidence="medium",
    reasons=("SOS 放量突破", "Markup 主升阶段"),
    watch_points=("次日不宜大幅回落至突破位下方", "量能需要维持或温和缩量承接"),
)

_ACCUM_REPAIR_RESONANCE = _EventSpec(
    event_id="accumulation_repair_resonance",
    label="吸筹修复共振",
    track="Accum",
    action="低位观察",
    confidence="medium",
    reasons=("Spring 修复", "缩量回踩或放量承接共振"),
    watch_points=("不能再次有效跌破交易区间下沿", "后续需要从修复转向放量上攻"),
)

_SPRING_RECLAIM = _EventSpec(
    event_id="spring_reclaim",
    label="Spring 修复",
    track="Accum",
    action="低位观察",
    confidence="medium",
    reasons=("假跌破后重新收回",),
    watch_points=("观察是否站回区间内部", "避免次日继续破位"),
)

_LPS_PULLBACK_CONFIRM = _EventSpec(
    event_id="lps_pullback_confirm",
    label="LPS 回踩确认",
    track="Accum",
    action="支撑观察",
    confidence="medium",
    reasons=("缩量回踩支撑",),
    watch_points=("回踩不应放量跌破支撑", "后续需要重新转强"),
)

_VOLUME_ABSORPTION = _EventSpec(
    event_id="volume_absorption",
    label="放量承接",
    track="Accum",
    action="承接观察",
    confidence="medium",
    reasons=("放量但价格不弱",),
    watch_points=("放量后不能快速转弱", "等待后续转为 SOS 或 LPS 确认"),
)

_SOS_WATCH = _EventSpec(
    event_id="sos_watch",
    label="SOS 观察",
    track="Trend",
    action="强度观察",
    confidence="medium",
    reasons=("SOS 信号",),
    watch_points=("确认突破是否有效", "高开过多不宜追"),
)

_WYCKOFF_WATCH = _EventSpec(
    event_id="wyckoff_watch",
    label="威科夫观察",
    track="Watch",
    action="观察",
    confidence="low",
    reasons=(),
    watch_points=("等待更多结构确认",),
)


def _norm_set(values: tuple[str, ...] | list[str] | set[str]) -> set[str]:
    return {str(x or "").strip().lower() for x in values if str(x or "").strip()}


def _base_reasons(stage: str, channel: str, regime: str, score: float) -> list[str]:
    reasons: list[str] = []
    if stage:
        reasons.append(f"阶段={stage}")
    if channel:
        reasons.append(f"通道={channel}")
    if regime:
        reasons.append(f"水温={regime}")
    if score:
        reasons.append(f"分数={float(score):.2f}")
    return reasons


def _event(
    *,
    spec: _EventSpec,
    base_reasons: list[str],
) -> WyckoffEvent:
    return WyckoffEvent(
        event_id=spec.event_id,
        label=spec.label,
        track=spec.track,
        action=spec.action,
        confidence=spec.confidence,
        reasons=tuple([*base_reasons, *spec.reasons]),
        watch_points=spec.watch_points,
    )


def _score_confidence(score: float, high_threshold: float) -> str:
    return "high" if score >= high_threshold else "medium"


def _event_spec(trigger_set: set[str], stage: str, score: float) -> _EventSpec:
    if "sos" in trigger_set and stage == "Markup":
        return replace(_RIGHT_SIDE_IGNITION, confidence=_score_confidence(score, 10))
    if "spring" in trigger_set and ("lps" in trigger_set or "evr" in trigger_set):
        return replace(_ACCUM_REPAIR_RESONANCE, confidence=_score_confidence(score, 5))
    if "spring" in trigger_set:
        return _SPRING_RECLAIM
    if "lps" in trigger_set:
        return _LPS_PULLBACK_CONFIRM
    if "evr" in trigger_set:
        return replace(_VOLUME_ABSORPTION, track="Trend" if stage == "Markup" else "Accum")
    if "sos" in trigger_set:
        return _SOS_WATCH
    return _WYCKOFF_WATCH


def classify_wyckoff_event(
    triggers: tuple[str, ...] | list[str] | set[str],
    *,
    stage: str = "",
    channel: str = "",
    score: float = 0.0,
    regime: str = "",
) -> WyckoffEvent:
    """Classify raw Wyckoff triggers into a readable event.

    The returned action is deliberately phrased as observation, not a trade
    instruction.  Trading decisions can later consume these event ids.
    """

    trigger_set = _norm_set(triggers)
    stage_s = str(stage or "").strip()
    channel_s = str(channel or "").strip()
    regime_s = str(regime or "").strip().upper()
    base_reasons = _base_reasons(stage_s, channel_s, regime_s, score)
    return _event(spec=_event_spec(trigger_set, stage_s, score), base_reasons=base_reasons)


__all__ = ["WyckoffEvent", "classify_wyckoff_event"]
