# A 股漏斗数据质量与诊断 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 A 股漏斗生产准入调整为 25 亿元/4000 万元，并为概念、通道、数据覆盖和报告诊断建立可测试的正式语义。

**Architecture:** 保持核心筛选函数纯粹，在独立的数据质量模块计算市值、财务和 OHLCV 覆盖率及 `normal/degraded`、`ready/observe_only` 状态。漏斗指标携带数据质量、数据源、RPS universe 和逐层淘汰统计；渲染和交付只消费这些结构化指标。

**Tech Stack:** Python 3.11、pandas、pytest、ruff。

## Global Constraints

- 生产默认值为 `min_market_cap_yi=25.0`、`min_avg_amount_wan=4000.0`。
- 数据质量不足时仍可生成观察报告，但不得把候选表述为正式可执行推荐。
- 保留 Layer 2 多标签，不引入互斥通道。
- 所有行为变更先写失败测试并确认 RED，再实现 GREEN。
- 必须通过 ruff、format、函数长度门禁和全量 pytest。

---

### Task 1: 核心筛选语义

**Files:**
- Modify: `core/wyckoff_engine.py`
- Modify: `core/layer2_strength.py`
- Test: `tests/test_wyckoff_engine.py`
- Test: `tests/test_layer2_strength.py`

**Interfaces:**
- Produces: `FunnelConfig` 新生产默认值；`_build_sector_groups()` 稳定去重；`channel_labels()` 无命中返回空列表。

- [x] 写默认参数、概念重复输入和空通道的失败测试。
- [x] 运行聚焦测试，确认失败原因分别是旧默认值、重复计数和错误兜底标签。
- [x] 最小修改生产实现。
- [x] 运行聚焦测试并确认通过。

### Task 2: 数据覆盖率门禁

**Files:**
- Create: `workflows/funnel_data_quality.py`
- Test: `tests/test_funnel_data_quality.py`

**Interfaces:**
- Consumes: 股票池代码、行情 DataFrame 映射、市值映射、财务映射及是否请求财务数据。
- Produces: `build_funnel_data_quality(...) -> dict`，包含三个覆盖率、状态、交易就绪度、原因和行情数据源占比。

- [x] 写正常覆盖、低市值覆盖、低财务覆盖、低 OHLCV 覆盖及数据源统计的失败测试。
- [x] 运行测试，确认模块缺失导致 RED。
- [x] 实现覆盖率和门禁：OHLCV/市值最低 95%，请求财务时最低 90%；不足即 `degraded + observe_only`。
- [x] 运行测试并确认通过。

### Task 3: 漏斗指标和淘汰诊断

**Files:**
- Modify: `workflows/funnel_layers.py`
- Modify: `workflows/wyckoff_funnel.py`
- Test: `tests/test_wyckoff_funnel_metrics.py`

**Interfaces:**
- Produces: `rps_universe_count`、`layer_rejections`、`data_quality`、`ohlcv_source_counts` 等结构化指标。

- [x] 写指标失败测试，覆盖 RPS 样本数以及 L1/L2/L3/L4 的输入、通过、淘汰数量与原因说明。
- [x] 运行测试并确认 RED。
- [x] 扩展层输出和指标聚合，复用 Task 2 门禁。
- [x] 运行测试并确认通过。

### Task 4: 报告 observe-only 语义

**Files:**
- Modify: `workflows/funnel_render.py`
- Modify: `workflows/wyckoff_funnel.py`
- Test: `tests/test_funnel_render.py`
- Test: `tests/test_wyckoff_funnel.py`

**Interfaces:**
- Consumes: `metrics["data_quality"]`、覆盖率、数据源和淘汰诊断。
- Produces: 报告中的数据质量、RPS universe、行情来源和逐层淘汰行；降级运行的 AI 候选保留为 shadow 观察，执行结论明确禁止正式推荐。

- [x] 写降级报告和 selection 标记的失败测试。
- [x] 运行测试并确认 RED。
- [x] 渲染诊断行，并在降级时把策略标记为 `observe_only`。
- [x] 运行测试并确认通过。

### Task 5: 全量验证

**Files:**
- Modify: `docs/superpowers/plans/2026-07-10-funnel-data-quality.md`

**Interfaces:**
- Produces: 可审计的验证结果。

- [x] 运行所有新增和受影响测试。
- [x] 运行 `.venv/bin/ruff check .`。
- [x] 运行 `.venv/bin/ruff format --check .`。
- [x] 运行 `.venv/bin/python scripts/quality_gate.py --ci`。
- [x] 运行 `.venv/bin/python -m pytest tests/ -q`。
- [x] 检查最终 diff、无调试产物且工作区只含本任务文件。
