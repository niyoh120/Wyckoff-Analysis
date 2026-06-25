# Architecture Refactor Plan

目标是把现有“能跑的脚本集合”整理成边界清晰的策略系统，并保持功能、性能和结果口径不折损。

## Target Boundaries

- `core/`: 纯业务规则、评分、信号生命周期和领域模型，不直接读写 Supabase、TickFlow、Feishu、Web 或进程环境变量。
- `integrations/`: 外部系统适配器，只负责 I/O、鉴权、字段清洗和错误归一化。
- `scripts/`: 命令行入口和调度胶水，只做参数解析、环境读取和 workflow 调用。
- `agents/`: Chat/MCP 工具编排层，不承载业务规则，不直接拼复杂 SQL 字段契约。
- `web/packages/shared/`: Web 与 API 共用的类型、工具执行和展示口径。
- `web/apps/*`: UI/API 入口，不复制后端业务判断。

## Migration Order

1. `tail_buy`: 已迁移为 `core/tail_buy/`，拆出模型、风控闸、报告渲染和策略评分；策略运行时阈值迁移到 `workflows/tail_buy_config.py`，核心评分只接收显式 `TailBuyStrategyConfig`。
2. `recommendation_tracking`: 已拆分“AI推荐”和“形态复盘观察”的领域模型及展示口径。
3. `wyckoff_funnel`: 漏斗主编排已从 `scripts/wyckoff_funnel.py` 迁移到 `workflows/wyckoff_funnel.py`，不保留脚本兼容壳；运行时配置解析迁移到 `workflows/funnel_settings.py`，候选策略运行环境解析迁移到 `workflows/candidate_policy_config.py`，`core/candidate_policy.py` 只接收显式 `CandidatePolicyConfig`，动态策略反馈环境解析迁移到 `workflows/dynamic_policy_config.py`，`core/dynamic_policy.py` 只接收显式 `DynamicPolicyConfig`，AI 候选配额环境解析迁移到 `workflows/ai_candidate_allocation_config.py`，AI 候选配额/轨道交替选择迁移到 `core/ai_candidate_allocation.py` 并只接收显式 `AiCandidateAllocationConfig`，Layer 2 基准/RPS/RS/通道标签纯计算迁移到 `core/layer2_strength.py`，L3 候选排名/触发器标签从历史 `tools/candidate_ranker.py` 迁移到 `core/candidate_ranker.py`，L1-L4 过层/板块轮动/主题雷达上下文迁移到 `workflows/funnel_layers.py`，主题雷达候选/加权/提升迁移到 `core/funnel_theme.py`，候选合并/轨道拆分/L2 旁路晋级迁移到 `core/funnel_selection.py`，候选池构造、战略L2旁路和 Alpha 候选输出迁移到 `workflows/funnel_candidates.py`，AI 候选分配、动态策略 shadow 和 review 候选提升迁移到 `workflows/funnel_ai_selection.py`，飞书卡片渲染、symbol rows 和 run details 迁移到 `workflows/funnel_render.py`，渲染上下文装配迁移到 `workflows/funnel_render_context.py`，候选输出字段合同迁移到 `core/funnel_report.py`，L4/趋势观察池报告分区迁移到 `core/funnel_sections.py`，数据准备/股票池/基准水温/快照编排迁移到 `workflows/funnel_data.py`，ETF 专属评分/展示迁移到 `core/funnel_etf.py`，ETF universe 解析迁移到 `integrations/funnel_etf_data.py`，ETF 行情拉取、过层和增强编排迁移到 `workflows/funnel_etf.py`，全量拉取快照落盘迁移到 `integrations/funnel_snapshot.py`。已删除无价值的 `core/funnel_pipeline.py` 转发桥；Agent/MCP 运行漏斗时通过 `pool_board` / `executor_mode` 显式参数传递股票池和执行模式，不再临时改写 `FUNNEL_POOL_*` 环境变量。
4. `backtest`: 已从 `scripts/backtest_runner.py` 抽出交易指标/分层诊断到 `core/backtest_metrics.py`，报告渲染迁移到 `core/backtest_report.py`，交易执行/价格回放/NAV 指标迁移到 `core/backtest_execution.py`，候选选择口径迁移到 `core/backtest_selection.py`，每日回放引擎迁移到 `core/backtest_replay.py`，准备好数据后的回测编排迁移到 `core/backtest_run.py`，绩效汇总/wbt 辅助指标/现金组合覆盖迁移到 `core/backtest_performance.py`，运行参数归一化和校验迁移到 `core/backtest_config.py`，公共默认值迁移到 `workflows/backtest_defaults.py`，CLI 参数定义迁移到 `workflows/backtest_cli.py`，Backtest Grid 稳健参数排名/周期风控口径迁移到 `core/backtest_grid_ranking.py`，股票池/snapshot/历史行情加载迁移到 `workflows/backtest_data.py`，美股 universe 文件加载迁移到 `integrations/market_universe.py`，14:55 分钟线入场价 TickFlow adapter 迁移到 `workflows/backtest_intraday.py`，数据加载 + core 引擎编排迁移到 `workflows/backtest.py`，CLI 产物写入迁移到 `workflows/backtest_artifacts.py`。`scripts/backtest_runner.py` 现在只保留入口参数解析、请求对象构造和 workflow 调用；`workflows.backtest` 只保留 `run_backtest_request(BacktestWorkflowRequest)` 单一入口，不再提供历史位置参数/散装 kwargs 兼容层；已删除无价值的 `core/backtester.py` re-export 桥接壳，调用方必须直连真实归属模块。
5. `tail_buy`: 持仓分钟级动作分析迁移到 `workflows/tail_buy_holdings.py`，由尾盘任务、每日 Step4 持仓诊断和独立持仓诊断脚本共用；`scripts/tail_buy_intraday_job.py` 不再保留持仓分析的重复实现。
6. `market_funnel`: 跨市场漏斗配置迁移到 `workflows/market_funnel_config.py`，港/美/ETF 漏斗任务和单票复盘诊断共用同一份配置函数。
7. `step3_step4`: Step3 AI 研报与 Step4 OMS 再平衡已从 `scripts/` 迁移到 `workflows/step3_batch_report.py` 和 `workflows/step4_rebalancer.py`，不保留脚本兼容壳；Agent、daily job、web background job 和 CLI 均调用 workflow 入口。Step4 target 解析、候选收口、通知通道检查和 OMS 摘要统一迁移到 `workflows/step4_pipeline.py`，`scripts/step4_from_supabase.py` 不再复用 `scripts/daily_job.py` 的内部函数。Step4 数据合同迁移到 `workflows/step4_models.py`，市场风控视图迁移到 `workflows/step4_market.py`，track/stage 文本归一迁移到 `workflows/step4_text.py`，LLM 决策 JSON 解析与组合限购迁移到 `workflows/step4_decision_parser.py`，持仓/候选量价 payload、ATR 和最新价上下文迁移到 `workflows/step4_payload.py`，确定性 OMS 订单引擎迁移到 `workflows/step4_order_engine.py`，交易工单渲染迁移到 `workflows/step4_ticket.py`；`workflows/step4_rebalancer.py` 只保留账户读取、模型调用、通知、持久化和工作流编排。
8. `public briefs`: 公共盘前简报与 Step3 合规简报保留在 `core/` 做脱敏 payload、fallback、校验和文本生成；LLM 路由、env 解析和调用函数分别迁移到 `workflows/premarket_public_brief_config.py`、`workflows/compliance_report_config.py` 与脚本入口注入。
9. `chat_tools`: 已抽出 Agent 文件/命令/Web 抓取安全校验到 `agents/tool_security.py`，本地工具实现迁移到 `agents/local_tools.py`；股票搜索迁移到 `agents/search_tools.py`；个股诊断/行情查询迁移到 `agents/diagnosis_tools.py`；大盘水温/回看迁移到 `agents/market_tools.py`；持仓查看/诊断/更新迁移到 `agents/portfolio_tools.py`；历史查询迁移到 `agents/history_tools.py`；回测工具入口迁移到 `agents/backtest_tools.py`；漏斗筛选迁移到 `agents/screen_tools.py`；AI 研报迁移到 `agents/report_tools.py`；策略决策迁移到 `agents/strategy_tools.py`；股票名称和行情元数据 helper 迁移到 `agents/stock_data_helpers.py`；Supabase user-client/auth retry 迁移到 `agents/tool_context.py`。`agents/chat_tools.py` 现在只保留 `WYCKOFF_TOOLS` 聚合列表。
10. `web chat`: 已拆分 conversation state、message/tool rendering、sidebar、dashboard shortcuts、watchlist panel、shared message types、watchlist/storage utils、chat transport/message queue、chat actions、transcript shell 和 header/composer 到 `web/apps/web/src/features/reading-room/`。`chat.tsx` 已从 2031 行降至 107 行，只保留页面状态装配、hook 组合和顶层布局；`tool-rendering.tsx` 继续拆出 `tool-rendering-model.ts` 和 `tool-structured-cards.tsx`，页面渲染层不再同时承载工具摘要模型与结构化结果卡片；`dashboard.tsx` 拆出 `dashboard-config.ts`，让场景/快捷入口文案与布局组件分离。
11. `supabase`: 内置 anon fallback 从 `core/constants.py` 迁移到 `integrations/supabase_public_config.py`；`core/` 不再保存外部连接凭据或读取运行时环境。

## Backtest Readout: 2026-06-21 Grid

- 最近 6 月窗口中，“二次确认买入 / 10天 / SL-8% / TP18% / 无 Trail”现金收益最高，为 `+53.17%`；跨周期稳健参数为“二次确认买入 / 15天 / SL-7% / TP18% / 无 Trail”，最近 6 月现金收益 `+45.98%`。
- `TP18%` 明显优于无止盈组合；无 Trail 目前优于移动止盈，说明这套候选的收益更像“快冲到目标位退出”，不是长期趋势跟随。
- “集中换股”在最近 6 月能涨，但回撤过大，最高档位现金回撤到 `-33%` 以上，不适合作为默认实盘风格。
- 熊市 2021-12-13 ~ 2022-10-31 全部参数组合为负，最好也只有 `-22.83%`；这不是入场微调能解决的问题，必须进入 regime 级风险闸。
- 飞书高密交易记录已能复盘最优组合的 47 笔交易；`core/backtest_grid_ranking.py` 统一 markdown 报告和飞书卡片的“稳健参数/风险折中/周期全负”判断，避免两个出口口径漂移。
- 2026-06-21 复盘发现现金组合层会把原始 `stop_loss/take_profit/time_exit` 覆盖成 `planned_exit`，收益不受影响，但卡片复盘会失真；已改为到期平仓保留原始退出原因，风格换股仍覆盖为 `style_swap`。
- 当前 SL/TP 回测使用日线 `high/low` 判定触发，并按阈值价或开盘跳空价成交。这适合参数相对比较，但偏乐观；需要补“保守成交/滑点”口径后再把 `TP18%` 作为实盘默认。
- 下一轮算法改造优先级：先做熊市/风险关闭仓和降频交易，再做二次确认的正式策略边界，最后才微调单票入场分。

## Review And Commit Packages

本轮重构改动面很大，提交前按包审查，避免把架构迁移、行为修复和 UI 拆分揉成不可回滚的巨型提交。

1. `quality/docs`: `AGENTS.md`、`docs/QUALITY_SYSTEM.md`、`docs/ARCHITECTURE_REFACTOR.md`、`.metrics/*`、`scripts/quality_gate.py`。
2. `agent tools`: `agents/*`、`mcp_server.py`、对应 `tests/test_*tool*` / chat tool 测试。
3. `web reading-room`: `web/apps/web/src/routes/chat.tsx`、`web/apps/web/src/features/reading-room/*`、`web/packages/shared/*`。
4. `backtest`: `core/backtest_*`、`workflows/backtest*`、`workflows/backtest_data.py`、`scripts/backtest_runner.py`、Backtest Grid workflow 和对应测试。
5. `funnel`: `workflows/wyckoff_funnel.py`、`workflows/funnel_*`、`core/funnel_*`、`core/layer2_strength.py`、`core/candidate_ranker.py`、ETF/market metadata adapters 和对应测试。
6. `tail-buy`: `core/tail_buy/*`、`workflows/tail_buy_*`、`scripts/tail_buy_intraday_job.py` 和对应测试。
7. `step3/step4`: `workflows/step3_batch_report.py`、`workflows/step4_*`、`scripts/daily_job.py`、`scripts/step4_from_supabase.py` 和对应测试。
8. `recommendation/supabase`: `integrations/recommendation_*`、`integrations/supabase_*` 拆分和对应持久化测试。
9. `cli/runtime`: `cli/*`、`utils/env.py`、`utils/json_text.py`、CLI/import guard 测试。

每个包至少检查三件事：旧路径引用是否清零、新模块是否有调用方或测试、入口脚本 `--help` 是否能渲染。跨包提交前再跑 full gate。

## Verification Gate

收口验证使用以下命令作为当前 full gate：

```bash
.venv/bin/ruff check .
.venv/bin/ruff format --check .
git diff --check
.venv/bin/python scripts/quality_gate.py --ci --verbose
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/ -x -q
corepack pnpm --dir web -r exec tsc --noEmit
corepack pnpm --dir web --filter @wyckoff/web test
corepack pnpm --dir web --filter @wyckoff/web build
```

脚本入口 smoke 已固化到 `tests/test_script_help_smoke.py`，覆盖本轮改动的 CLI/脚本 `--help` 渲染，防止 argparse 文案或入口导入在测试外悄悄损坏。

## Rules

- 不新增只转发一次调用的 wrapper；冗余抽象属于 review 强约束，不作为机器硬判定。
- 每次迁移必须删除旧路径或更新所有调用方，不保留无价值兼容层。
- 先补 characterization tests，再迁移文件和函数。
- 新函数以 50 行为设计目标；硬上限按 `scripts/quality_gate.py` 的分层规则执行。迁移遗留长函数时优先拆短，不扩大白名单。
- 表字段契约集中到模型或 adapter，业务层不散落 `.select("...")` 字符串。
- LOC 门禁已经把 active function 归零，但 Python/TS 总 LOC 仍有增长警告；后续每刀优先删除重复与无价值胶水，不用新增兼容层掩盖旧边界。质量体系采用 fast gate / full gate 分层：本地快速反馈不替代 CI 全量契约，CI 也不机械判断冗余抽象。
