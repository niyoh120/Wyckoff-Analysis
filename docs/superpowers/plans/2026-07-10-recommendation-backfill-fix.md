# 推荐与尾盘候选安全回刷 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复回刷模式与数据质量门禁的冲突，并安全重建最近 15 个交易日的线上候选数据。

**Architecture:** 复用现有 `recommendation_backfill` 的日期级备份、dry-run、空日期保护和替换流程。回刷调用显式关闭财务请求，使财务覆盖率不参与门禁；artifact 明确记录“历史价格 + 当前元数据”的运营重建口径，避免被当作严格点时回测。

**Tech Stack:** Python 3.11、pytest、Supabase、ruff。

## Global Constraints

- 先 dry-run 并检查 artifact，禁止未经检查直接写库。
- 默认空日期阻断，除非人工明确允许。
- 回刷只覆盖最近 15 个交易日对应日期，不改更早历史。
- 写库前保留旧 `recommendation_tracking` 行备份。
- 写库后核验目标日期数量、`signal_pending` 数量和应用摘要。

---

### Task 1: 修复回刷运行口径

**Files:**
- Modify: `workflows/recommendation_backfill.py`
- Test: `tests/test_recommendation_backfill.py`

**Interfaces:**
- Produces: `_build_day_result()` 以 `include_financial_metrics=False` 调用漏斗；summary/artifact 包含 `replay_context`。

- [ ] 写失败测试，断言回刷显式关闭财务请求。
- [ ] 写失败测试，断言 summary 标记历史价格、当前元数据、动态策略关闭和财务请求关闭。
- [ ] 运行测试确认 RED。
- [ ] 实现最小修复并运行测试确认 GREEN。

### Task 2: 验证代码

**Files:**
- Modify: `docs/superpowers/plans/2026-07-10-recommendation-backfill-fix.md`

**Interfaces:**
- Produces: 可审计的回刷代码验证结果。

- [ ] 运行回刷与数据质量聚焦测试。
- [ ] 运行 ruff、format、quality gate 和全量 pytest。
- [ ] 检查 diff 和工作区范围。

### Task 3: Dry-run 与线上回刷

**Files:**
- Generate: `artifacts/recommendation_backfill/*`

**Interfaces:**
- Produces: 最近 15 个交易日新旧候选对比、旧行备份和线上替换摘要。

- [ ] 不带 `--apply` 运行最近 15 个交易日回刷。
- [ ] 检查空日期、每日新旧数量、候选变化和辅助表行数。
- [ ] dry-run 合格后带 `--apply` 执行同一日期集合。
- [ ] 检查 `apply_summary.json` 并重新查询线上目标日期。
- [ ] 删除不需要提交的运行 artifact，提交并推送代码修复。
