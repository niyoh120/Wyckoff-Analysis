# A 股回测报告口径

> 本文件用于说明当前 Backtest Grid 的生产口径。单次完整参数矩阵以 GitHub Actions artifact 为准；本页只保留最近一次人工校验样例，避免旧 artifact 被误当成当前策略结论。

## 当前生产口径

- 工作流：`.github/workflows/backtest_grid.yml`
- 回测脚本：`python -m scripts.backtest_runner`
- 股票池：`main_chinext`，主板 + 创业板，剔除 ST
- 默认资金：`100000`
- 最大持仓：`4`
- 买入：T 日收盘后产生信号，T+1 `14:55` 分钟线价格买入
- fallback：分钟线缺失时由 `BACKTEST_ENTRY_PRICE_FALLBACK` 控制，默认 `close`
- 手续费：买卖双边万分之 2，单笔成交额低于 `10000` 元时固定收 `5` 元
- 候选池：`FUNNEL_AI_SELECTION_MODE=all_formal_l4`，只回放正式 L4 命中候选，不再把 L3 补位当成 `Layer3_Backup`
- 约束：T+1、一字板不可成交、卖出后才能补位、最多持有 4 只

## 最近一次链路校验

本地使用 GitHub Actions snapshot 回放熊市区间，验证修正后的候选口径、现金账户和 `14:55` 入场链路可以跑通。

| 项目 | 值 |
|------|----|
| 区间 | 2021-12-13 ~ 2022-10-31 |
| 参数 | 持有 5 天 / SL-6% / 无 TP / 无 Trail |
| TopN | 4 |
| 成交样本 | 151 |
| 单笔胜率 | 23.18% |
| 单笔均收 | -2.129% |
| 最大回撤 | -59.64% |
| 初始现金 | 100000.00 |
| 最终现金 | 64552.79 |
| 现金收益 | -35.45% |
| 入场价格来源 | `daily_close_fallback=151` |

这次结果说明两件事：

1. 链路已按新口径收紧，旧报告里的 `Layer3_Backup` 不能再作为有效分类使用。
2. 样例仍然全部落到日收盘 fallback，说明当前 snapshot 没有真实 14:55 分钟线；如果要验证真实尾盘成交，需要使用包含分钟线的数据源或把 fallback 改成 `skip` 做严格回测。

## 解读边界

- 胜率是单笔交易 `ret_pct > 0` 的比例，不是组合每日正收益比例。
- 当前回测仍可能包含股票池幸存者偏差；历史退市股不在当前在市样本里。
- 市值/行业映射如果使用当前截面，会引入 look-ahead bias；历史研究应优先关闭当前截面过滤或补历史元数据。
- 本文件不是收益承诺；它只用于校验策略口径、参数方向和市场周期适配。

## 后续维护

- 每次 Backtest Grid 完成后，优先查看对应 Actions artifact 的 `summary_*.md`、`trades_*.csv` 和飞书卡片。
- 若要更新本页，应只写入已经确认过的生产口径或明确标注为“样例”的回测结果。
- 如果 `entry_price_source_counts` 长期显示 `daily_close_fallback`，不要把结果解读成真实 14:55 成交表现。
