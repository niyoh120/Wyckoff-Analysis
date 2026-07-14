from __future__ import annotations

from pathlib import Path

from workflows.backtest_market_report_artifacts import load_grid_cells
from workflows.backtest_walk_forward import build_walk_forward_validation

PERIODS = {
    "bull_2020": ("2020-07-01", "2021-02-18"),
    "bear_2022": ("2021-12-13", "2022-10-31"),
    "recent_6m": ("2026-01-01", "2026-06-30"),
}


def _cell(root: Path, period: str, hold: int, cash_return: float) -> None:
    start, end = PERIODS[period]
    artifact = root / f"backtest-grid-{period}-h{hold}-sl-7-tp0-tr0"
    artifact.mkdir()
    (artifact / f"summary_{period}_h{hold}.md").write_text(
        "\n".join(
            [
                f"- 区间: {start} ~ {end}",
                "- 每日候选上限: Top 4",
                "- 股票池: all (sample=0)",
                "- 成交样本: 20",
                "- 胜率: 50%",
                "- 初始现金: 100000",
                f"- 最终现金: {100000 * (1 + cash_return / 100):.2f}",
                f"- 总收益: {cash_return}%",
                "- 成交笔数: 10",
            ]
        ),
        encoding="utf-8",
    )


def _grid(root: Path, returns: dict[int, tuple[float, float, float]]) -> None:
    for hold, values in returns.items():
        for period, value in zip(PERIODS, values, strict=True):
            _cell(root, period, hold, value)


def test_walk_forward_uses_train_winner_without_reoptimizing_test_period(tmp_path: Path) -> None:
    _grid(tmp_path, {10: (8.0, -2.0, 3.0), 15: (4.0, 6.0, 5.0)})

    result = build_walk_forward_validation(load_grid_cells(tmp_path))

    assert result["status"] == "fail"
    assert result["evaluated_window_count"] == 2
    assert result["windows"][0]["selected_params"]["hold_days"] == 10
    assert result["windows"][0]["test_cash_return"] == -2.0
    assert result["windows"][1]["selected_params"]["hold_days"] == 15
    assert result["windows"][1]["test_cash_return"] == 5.0


def test_walk_forward_passes_when_each_train_winner_survives_next_window(tmp_path: Path) -> None:
    _grid(tmp_path, {10: (8.0, 2.0, 3.0), 15: (4.0, 6.0, 5.0)})

    result = build_walk_forward_validation(load_grid_cells(tmp_path))

    assert result["status"] == "pass"
    assert result["positive_test_count"] == 2
