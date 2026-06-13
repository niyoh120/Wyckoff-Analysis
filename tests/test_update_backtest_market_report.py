from __future__ import annotations


def test_market_report_includes_cash_account_metrics(tmp_path):
    from scripts.update_backtest_market_report import build_report, load_grid_cells

    artifact = tmp_path / "backtest-grid-h5-sl-6-tp0-tr0-37"
    artifact.mkdir()
    (artifact / "summary_20211213_20221031_h5_n4.md").write_text(
        "\n".join(
            [
                "# Wyckoff Funnel Daily Backtest",
                "",
                "- 区间: 2021-12-13 ~ 2022-10-31",
                "- 持有周期: 5 交易日",
                "- 每日候选上限: Top 4",
                "- 股票池: main_chinext (sample=0)",
                "- 绩效引擎: auto（wbt 可用）",
                "- 成交样本: 249",
                "",
                "## 收益统计",
                "- 胜率: 29.32%",
                "- 平均收益: -1.520%",
                "- 中位收益: -5.984%",
                "",
                "## 组合风险指标（单利口径 · 基于每日净值曲线）",
                "- 夏普比 (Sharpe Ratio): -1.040",
                "- 卡玛比 (Calmar Ratio): -0.563",
                "- 最大回撤: -66.98%",
                "- 组合总收益: -32.16%",
                "",
                "## 真实现金账户模拟",
                "- 初始现金: 100000.00",
                "- 最终现金: 53785.51",
                "- 总收益: -46.21%",
                "- 成交笔数: 151",
                "- 佣金合计: 1011.52",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (artifact / "trades_20211213_20221031_h5_n4.csv").write_text(
        "signal_date,ret_pct,regime,trigger\n2022-01-01,-1.2,NEUTRAL,lps\n",
        encoding="utf-8",
    )

    cells = load_grid_cells(tmp_path)
    assert cells[0].cash_initial == 100000.0
    assert cells[0].cash_final == 53785.51

    report = build_report(cells)

    assert "现金账户: 初始 **100000.00**；最终 **53785.51**；盈亏 **-46214.49**" in report
    assert "| 排名 | 参数组合 | 夏普 | 胜率 | 均收 | 回撤 | 最终现金 | 现金收益 | 样本 |" in report


def test_market_report_groups_multi_period_grid(tmp_path):
    from scripts.update_backtest_market_report import build_report, load_grid_cells

    for period, start, end, cash_return, sharpe in [
        ("recent_6m", "2025-12-01", "2026-05-31", 2.5, 0.3),
        ("bull_2020", "2020-07-01", "2021-02-18", 16.9, 0.8),
        ("bear_2022", "2021-12-13", "2022-10-31", 13.6, -1.3),
    ]:
        artifact = tmp_path / f"backtest-grid-{period}-h10-sl-6-tp0-tr0-37"
        artifact.mkdir()
        (artifact / f"summary_{start.replace('-', '')}_{end.replace('-', '')}_h10_n4.md").write_text(
            "\n".join(
                [
                    "# Wyckoff Funnel Daily Backtest",
                    "",
                    f"- 区间: {start} ~ {end}",
                    "- 每日候选上限: Top 4",
                    "- 股票池: main_chinext (sample=0)",
                    "- 绩效引擎: legacy",
                    "- 成交样本: 10",
                    "- 胜率: 40.0%",
                    "- 平均收益: 1.0%",
                    "- 中位收益: 0.5%",
                    "- 夏普比 (Sharpe Ratio): " + str(sharpe),
                    "- 卡玛比 (Calmar Ratio): 0.1",
                    "- 最大回撤: -10.0%",
                    "- 组合总收益: 1.0%",
                    "- 初始现金: 100000.00",
                    "- 最终现金: 110000.00",
                    f"- 总收益: {cash_return}%",
                    "- 成交笔数: 4",
                    "- 佣金合计: 20.00",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

    cells = load_grid_cells(tmp_path)
    assert {cell.period_key for cell in cells} == {"recent_6m", "bull_2020", "bear_2022"}

    report = build_report(cells)

    assert "## 各周期最佳" in report
    assert "最近6个月: 2025-12-01 ~ 2026-05-31 (1组)" in report
    assert "牛市 2020-07~2021-02" in report
    assert "熊市 2021-12~2022-10" in report


def test_market_report_expands_cash_portfolio_styles(tmp_path):
    from scripts.update_backtest_market_report import build_report, load_grid_cells

    artifact = tmp_path / "backtest-grid-recent_6m-h10-sl-6-tp0-tr0-37"
    artifact.mkdir()
    (artifact / "summary_20251201_20260531_h10_n4.md").write_text(
        "\n".join(
            [
                "# Wyckoff Funnel Daily Backtest",
                "",
                "- 区间: 2025-12-01 ~ 2026-05-31",
                "- 每日候选上限: Top 4",
                "- 股票池: main_chinext (sample=0)",
                "- 绩效引擎: legacy",
                "- 成交样本: 10",
                "- 胜率: 40.0%",
                "- 平均收益: 1.0%",
                "- 中位收益: 0.5%",
                "- 夏普比 (Sharpe Ratio): 0.3",
                "- 卡玛比 (Calmar Ratio): 0.1",
                "- 最大回撤: -10.0%",
                "- 组合总收益: 1.0%",
                "- 初始现金: 100000.00",
                "- 最终现金: 101000.00",
                "- 总收益: 1.0%",
                "- 成交笔数: 4",
                "- 佣金合计: 20.00",
                "",
                "## 交易风格对比",
                "",
                "| 风格ID | 风格 | 最终现金 | 总收益 | 成交 | 胜率 | 平均盈利 | 平均亏损 | 加仓 | 换股 | 观察未确认 | 跳过 |",
                "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
                "| slot_equal_4 | 等额四仓 | 101000.00 | +1.00% | 4 | 50.00% | 3.0% | -1.0% | 0 | 0 | 0 | 1 |",
                "| probe_add | 观察仓补仓 | 112000.00 | +12.00% | 6 | 66.67% | 4.0% | -0.5% | 2 | 0 | 0 | 2 |",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    cells = load_grid_cells(tmp_path)
    assert [(cell.portfolio_style, cell.cash_total_return) for cell in cells] == [
        ("slot_equal_4", 1.0),
        ("probe_add", 12.0),
    ]

    report = build_report(cells)

    assert "## 各交易风格最佳" in report
    assert "观察仓补仓 / 10天 / SL-6% / 无TP / 无Trail" in report
