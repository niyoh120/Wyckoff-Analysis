from pathlib import Path

from workflows.backtest_strategy_comparison import (
    build_strategy_comparison,
    load_strategy_comparison_rows,
    render_strategy_comparison,
)


def _write_summary(root: Path, period: str, variant: str, cash_return: float, drawdown: float) -> None:
    target = root / f"backtest-strategy-{period}-{variant}"
    target.mkdir(parents=True)
    (target / "summary_fixture.md").write_text(
        "\n".join(
            [
                "# Wyckoff Funnel Daily Backtest",
                "- 区间: 2020-01-01 ~ 2020-06-30",
                "- 策略消融组: " + variant,
                "- 平均收益: 1.25%",
                "- 夏普比 (Sharpe Ratio): 1.5",
                "- 成交样本: 30",
                "## 真实现金账户模拟",
                f"- 总收益: {cash_return}%",
                f"- 现金最大回撤: {drawdown}%",
                "- 成交笔数: 24",
                "- 胜率: 55%",
            ]
        ),
        encoding="utf-8",
    )


def test_strategy_comparison_builds_relative_and_walk_forward_results(tmp_path: Path) -> None:
    periods = ["bull_2020", "bear_2022", "recent_6m"]
    for period_index, period in enumerate(periods):
        for variant_index, variant in enumerate("ABCDE"):
            _write_summary(tmp_path, period, variant, 2.0 + variant_index + period_index, -4.0)

    rows = load_strategy_comparison_rows(tmp_path)
    report = build_strategy_comparison(rows)

    assert len(rows) == 15
    assert report["status"] == "ready"
    assert report["evaluations"]["E"]["status"] == "pass"
    assert len(report["walk_forward"]["windows"]) == 2
    assert "相对 A 组结论" in render_strategy_comparison(report)
