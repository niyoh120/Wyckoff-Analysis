# 推荐与尾盘候选生产回刷工作流设计

## 目标

在 GitHub Actions 的生产数据源和 Supabase Secrets 环境中，安全重建最近 15 个交易日的 `recommendation_tracking`、`signal_pending` 及相关辅助表。

## 方案

新增手动工作流 `Recommendation Backfill`，输入 `latest`、可选 `anchor` 和布尔值 `apply`。默认 `apply=false`，只执行 dry-run；工作流固定跳过 Step3 LLM，避免用当前模型事后改写历史 AI 判断。无论成功失败都上传 artifact，其中包含旧行备份、每日新旧数量、生成候选和辅助表统计。

`apply=true` 使用完全相同的脚本和日期解析，仅在 dry-run artifact 经人工检查后触发。脚本已有空日期保护，未显式允许时不会用空结果删除旧数据。

## 数据口径

- K 线按目标交易日截断。
- 市值、概念等元数据使用当前快照，因此这是运营候选刷新，不是严格点时回测。
- 回刷显式设置 `include_financial_metrics=False`，财务覆盖率不参与数据质量门禁。
- 动态策略关闭，使用当前代码中的静态正式策略。
- 回刷范围以最近 15 个交易日为限，更早历史不替换。

## 安全边界

- 专用 concurrency group 防止两个回刷互相覆盖。
- `apply` 必须由 workflow dispatch 显式选择。
- 工作流不发送日常漏斗通知，不运行 Step4 或尾盘下单任务。
- apply 前的 artifact 保留旧 `recommendation_tracking` 行；apply 后生成 `apply_summary.json`。
- 写后需比对目标日期、插入/删除数量并查询线上数据。

## 验证

- 单元测试覆盖回刷关闭财务请求、artifact 数据口径和工作流默认 dry-run/上传 artifact。
- 提交前运行 ruff、format、质量门禁和全量 pytest。
- 先触发 dry-run 并检查 artifact，再触发 apply，最后核验数据库。
