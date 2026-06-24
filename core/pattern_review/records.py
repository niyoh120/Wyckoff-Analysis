from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

AI_RECOMMENDATION_ROLE = "AI推荐"
PATTERN_REVIEW_ROLE = "观察/信号复盘"


def _as_text(value: Any) -> str:
    return "" if value is None else str(value)


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "t", "yes", "y", "ai", "ai推荐"}
    return bool(value)


@dataclass(frozen=True)
class PatternReviewRecord:
    code: str
    name: str
    recommend_date: str
    recommend_price: Any
    current_price: Any
    pnl_pct: Any
    max_pnl_pct: Any
    camp: str
    status: str
    is_ai_recommended: bool

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> PatternReviewRecord:
        return cls(
            code=_as_text(row.get("code")),
            name=_as_text(row.get("name")),
            recommend_date=_as_text(row.get("recommend_date")),
            recommend_price=row.get("recommend_price"),
            current_price=row.get("current_price"),
            pnl_pct=row.get("pnl_pct"),
            max_pnl_pct=row.get("max_pnl_pct"),
            camp=_as_text(row.get("camp")),
            status=_as_text(row.get("status")),
            is_ai_recommended=_as_bool(row.get("is_ai_recommended")),
        )

    @property
    def entry_role(self) -> str:
        return AI_RECOMMENDATION_ROLE if self.is_ai_recommended else PATTERN_REVIEW_ROLE

    def to_tool_record(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "name": self.name,
            "recommend_date": self.recommend_date,
            "recommend_price": self.recommend_price,
            "current_price": self.current_price,
            "pnl_pct": self.pnl_pct,
            "max_pnl_pct": self.max_pnl_pct,
            "camp": self.camp,
            "status": self.status,
            "is_ai_recommended": self.is_ai_recommended,
            "entry_role": self.entry_role,
        }


def pattern_review_tool_records(rows: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [PatternReviewRecord.from_row(row).to_tool_record() for row in rows]
