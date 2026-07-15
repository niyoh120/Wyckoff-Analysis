"""Shared ranking policy for Backtest Grid reports."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Hashable, Sequence
from dataclasses import dataclass
from statistics import mean
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class RobustParamScore(Generic[T]):
    key: Hashable
    cells: tuple[T, ...]
    best_cell: T
    score: float
    period_count: int
    positive_periods: int
    avg_cash_return: float | None
    min_cash_return: float | None
    recent_cash_return: float | None
    values: tuple[float, ...]


@dataclass(frozen=True)
class PeriodGuardrail:
    period_key: str
    best_value: float


def rank_robust_params(
    cells: Sequence[T],
    *,
    key_fn: Callable[[T], Hashable],
    period_fn: Callable[[T], str],
    value_fn: Callable[[T], float | None],
    representative_fn: Callable[[list[T]], T],
    recent_period: str | None = None,
    period_rank_fn: Callable[[str], tuple[int, str]] | None = None,
) -> list[RobustParamScore[T]]:
    groups: dict[Hashable, list[T]] = defaultdict(list)
    for cell in cells:
        groups[key_fn(cell)].append(cell)
    resolved_recent_period = recent_period or _resolve_recent_period(cells, period_fn, period_rank_fn)
    scores = [
        _score_param_group(key, group, period_fn, value_fn, representative_fn, resolved_recent_period)
        for key, group in groups.items()
    ]
    return sorted((s for s in scores if s.values), key=lambda item: item.score, reverse=True)


def robust_label(score: RobustParamScore[object] | None) -> str:
    if score is None:
        return "最优参数（按现金收益）"
    if score.period_count < 3:
        return "候选参数（周期覆盖不足）"
    if (
        score.period_count >= 3
        and score.min_cash_return is not None
        and score.min_cash_return > 0
        and score.positive_periods == score.period_count
    ):
        return "稳健参数（跨周期全正）"
    if score.score > 0 and score.positive_periods >= max(1, score.period_count - 1):
        return "折中参数（跨周期惩罚）"
    return "风险折中参数（熊市未通过）"


def weak_period_guardrails(
    cells: Sequence[T],
    *,
    period_fn: Callable[[T], str],
    value_fn: Callable[[T], float | None],
) -> list[PeriodGuardrail]:
    groups: dict[str, list[float]] = defaultdict(list)
    for cell in cells:
        value = value_fn(cell)
        if value is not None:
            groups[period_fn(cell)].append(value)
    guards = [PeriodGuardrail(period, max(values)) for period, values in groups.items() if values and max(values) <= 0]
    return sorted(guards, key=lambda item: item.period_key)


def _score_param_group(
    key: Hashable,
    group: list[T],
    period_fn: Callable[[T], str],
    value_fn: Callable[[T], float | None],
    representative_fn: Callable[[list[T]], T],
    recent_period: str,
) -> RobustParamScore[T]:
    by_period = _best_cells_by_period(group, period_fn, value_fn)
    values = tuple(value for cell in by_period.values() if (value := value_fn(cell)) is not None)
    recent_cell = by_period.get(recent_period)
    recent_ret = value_fn(recent_cell) if recent_cell is not None else None
    positives = sum(1 for value in values if value > 0)
    return RobustParamScore(
        key=key,
        cells=tuple(group),
        best_cell=representative_fn(group),
        score=_robust_score(values, recent_ret, positives),
        period_count=len(by_period),
        positive_periods=positives,
        avg_cash_return=mean(values) if values else None,
        min_cash_return=min(values) if values else None,
        recent_cash_return=recent_ret,
        values=values,
    )


def _best_cells_by_period(
    group: list[T],
    period_fn: Callable[[T], str],
    value_fn: Callable[[T], float | None],
) -> dict[str, T]:
    by_period: dict[str, T] = {}
    for cell in group:
        key = period_fn(cell)
        if key not in by_period or _rank_value(value_fn(cell)) > _rank_value(value_fn(by_period[key])):
            by_period[key] = cell
    return by_period


def _resolve_recent_period(
    cells: Sequence[T],
    period_fn: Callable[[T], str],
    period_rank_fn: Callable[[str], tuple[int, str]] | None,
) -> str:
    period_keys = {period_fn(cell) for cell in cells}
    if not period_keys:
        return "recent_6m"
    if period_rank_fn is None:
        return "recent_6m" if "recent_6m" in period_keys else sorted(period_keys)[0]
    return min(period_keys, key=period_rank_fn)


def _robust_score(values: tuple[float, ...], recent_ret: float | None, positive_periods: int) -> float:
    if not values:
        return float("-inf")
    return min(values) + mean(values) * 0.35 + (recent_ret or 0.0) * 0.2 + positive_periods * 4.0


def _rank_value(value: float | None) -> float:
    return value if value is not None else float("-inf")
