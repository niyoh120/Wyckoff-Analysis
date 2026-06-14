# A 股主漏斗执行流程

> 本文描述 A 股 Wyckoff 主漏斗从 GitHub Actions 触发到 Supabase 写库、跨日反馈闭环的完整执行链路。策略逻辑详见 [`../README_STRATEGY.md`](../README_STRATEGY.md)，架构与数据表详见 [`ARCHITECTURE.md`](ARCHITECTURE.md)。

**主入口**：`.github/workflows/wyckoff_funnel.yml` → `scripts/daily_job.py`（周日到周四 **17:17** 北京时间；仅次日为 A 股交易日时继续）

---

## 一、系统全景：上下游关系

```mermaid
flowchart TB
    subgraph UPSTREAM["⬆️ 上游（漏斗运行前已存在）"]
        U1["GitHub Actions 触发<br/>wyckoff_funnel.yml<br/>周日到周四 17:17 北京"]
        U2["环境变量 / Secrets<br/>TICKFLOW / TUSHARE / LLM / Supabase / IM"]
        U3["本地元数据<br/>行业映射 / 概念映射 / 股票池"]
        U4["前日反馈闭环<br/>signal_health_daily<br/>signal_registry"]
        U5["前日盘前风控<br/>premarket_risk → market_signal_daily"]
        U6["前日漏斗产出<br/>signal_pending 待确认信号"]
        U7["外部观察名单<br/>profile / env / symbols_file"]
    end

    subgraph CORE["🔬 核心：daily_job.py"]
        S2["Step2 Wyckoff Funnel<br/>scripts/wyckoff_funnel.py"]
        S25["Step2.5 信号确认<br/>pending → confirmed"]
        S26["Step2.6 推荐写库<br/>recommendation_tracking"]
        S27["Step2.7 起跳板 A/B/C 评分"]
        S3["Step3 批量 AI 研报<br/>scripts/step3_batch_report.py"]
        S4["Step4 私人 OMS 再平衡<br/>scripts/step4_rebalancer.py"]
    end

    subgraph DOWNSTREAM["⬇️ 下游（漏斗运行后消费）"]
        D1["23:30 signal_feedback_job<br/>计算 outcomes / health / registry"]
        D2["次日 08:20 premarket_risk<br/>Step4 买入门控"]
        D3["次日 13:50 tail_buy_intraday<br/>读 signal_pending 尾盘买入"]
        D4["Web / CLI / MCP<br/>chat-agent 工具调用"]
        D5["回测 backtest_runner<br/>读 funnel_snapshots"]
        D6["recommendation_tracking_reprice<br/>复盘重定价"]
        D7["飞书 / 企微 / 钉钉 / Telegram"]
    end

    U1 --> CORE
    U2 --> CORE
    U3 --> S2
    U4 --> S2
    U5 --> S4
    U6 --> S25
    U7 --> S2

    S2 --> S25 --> S26 --> S27 --> S3 --> S4

    S2 --> D7
    S3 --> D7
    S4 --> D7

    S2 --> D1
    S3 --> D1
    S4 --> D2
    S25 --> D3
    S26 --> D6
    S2 --> D5
    CORE --> D4
```

---

## 二、主入口：`daily_job.py` 完整执行链

**触发**：`.github/workflows/wyckoff_funnel.yml` → `python scripts/daily_job.py`

```mermaid
flowchart TD
    START(["GitHub Actions 17:17<br/>wyckoff_funnel.yml"]) --> CHECK1{"配置校验<br/>LLM Key / Model"}
    CHECK1 -->|缺失| FAIL1["exit 1"]
    CHECK1 -->|通过| CHECK2{"次日交易日判定<br/>明日是否 A 股交易日?"}
    CHECK2 -->|否| SKIP["IM 通知跳过<br/>exit 0"]
    CHECK2 -->|是| STEP2

    STEP2["Step2: run_funnel()<br/>wyckoff_funnel.py"] --> P1["写 market_signal_daily<br/>大盘水温 regime"]
    STEP2 --> P2["写 theme_radar_snapshot<br/>主题雷达"]
    STEP2 --> S25

    S25["Step2.5: run_step2_5()<br/>signal_pending 确认"] --> S26
    S26["Step2.6: prepare_recommendation_payload<br/>→ recommendation_tracking"] --> S27
    S27["Step2.7: score_springboard_abc<br/>起跳板量化评分"] --> S3

    S3["Step3: run_step3()<br/>批量 AI 研报"] --> MARK["mark_ai_recommendations<br/>标记起跳板"]
    MARK --> OBS["写 signal_observations<br/>L4 观察样本"]

    S3 --> S4CHK{"Step4 启用?<br/>SUPABASE_USER_ID + TG"}
    S4CHK -->|跳过| SUM
    S4CHK -->|执行| S4

    S4["Step4: run_step4()<br/>持仓决断 + Telegram"] --> SUM
    SUM["阶段汇总日志<br/>upload artifacts"] --> END(["exit 0/1"])

    STEP2 -->|异常| BLOCK["阻断型失败 exit 1"]
    OBS -->|失败| BLOCK
```

### 阶段与代码映射

| 阶段 | 入口 | 核心模块 |
|------|------|----------|
| 调度 | `wyckoff_funnel.yml` | GitHub Actions |
| 编排 | `scripts/daily_job.py` | 主流程 |
| Step2 | `scripts/wyckoff_funnel.py` | `core/wyckoff_engine.py` |
| Step3 | `scripts/step3_batch_report.py` | `tools/report_builder.py` |
| Step4 | `scripts/step4_rebalancer.py` | `core/strategy.py`（转发） |

---

## 三、Step2 漏斗内部：L0 → L5 详细流程

**核心函数**：`run_funnel_job()` → `core/wyckoff_engine.py`

```mermaid
flowchart TD
    subgraph PREP["阶段 0：数据准备"]
        P0["解析交易日窗口<br/>320 个交易日"]
        P1["加载股票池<br/>主板 + 创业板 → 去 ST"]
        P2["加载元数据<br/>行业 / 概念 / 概念热度 / 市值 / 名称"]
        P3["TickFlow 财务指标<br/>financial_map"]
        P4["拉取基准指数<br/>000001 + 小盘指数"]
        P5["fetch_all_ohlcv 批量拉 K 线<br/>TickFlow → tushare → akshare → baostock → efinance"]
        P6["dump funnel_snapshots<br/>离线快照"]
        P7["ETF 增强扫描<br/>_run_etf_enhancement"]
        P8["加载 external_seeds<br/>追加到观察池"]
    end

    subgraph GATE["阶段 0.5：大盘总闸"]
        G1["calc_market_breadth<br/>市场广度"]
        G2["analyze_benchmark_and_tune_cfg<br/>regime 判定"]
        G3{"水温 regime"}
        G3 -->|NEUTRAL| T1["默认门槛"]
        G3 -->|RISK_ON| T2["适度放宽"]
        G3 -->|RISK_OFF| T3["提高门槛"]
        G3 -->|CRASH| T4["极限门槛 + 悬崖检测"]
    end

    subgraph LAYERS["五层漏斗"]
        L1["L1 layer1_filter<br/>主板/创业板 · 非 ST · 市值≥35亿<br/>成交额≥5000万 · 财务过滤"]
        L2["L2 layer2_strength_detailed<br/>六通道并行"]
        L2A["主升 Markup"]
        L2B["点火 SOS Bypass"]
        L2C["潜伏 Ambush"]
        L2D["吸筹 Accumulation"]
        L2E["地量 Dry Volume"]
        L2F["暗中护盘 RS Divergence"]
        L3["L3 layer3_sector_resonance<br/>板块共振 + 概念主线<br/>+ ETF L2 注入"]
        L4["L4 layer4_triggers<br/>SOS / Spring / LPS / EVR / Compression"]
        L5["L5 layer5_exit_signals<br/>派发 / 止损预警"]
    end

    subgraph BYPASS["旁路池（不进正式 L4 主路径）"]
        B1["L2 明珠旁路<br/>L1过 + L2拒 + 热门板块 + L4"]
        B2["战略 L2 旁路<br/>主题雷达观察池 + 阶段复核"]
    end

    subgraph POST["后处理 & 候选分配"]
        R1["watch_score 排序 L3"]
        R2["Markup / Accum ABC 阶段识别"]
        R3["主题雷达 theme_radar 构建"]
        R4["候选评分 + 双轨分配"]
        R4A["Trend 轨：主升 + 点火"]
        R4B["Accum 轨：潜伏 + 吸筹 + 地量 + 护盘"]
        R5{"FUNNEL_AI_SELECTION_MODE"}
        R5 -->|all_formal_l4| R6["正式 L4 全量送 AI<br/>不含 L3 补位"]
        R5 -->|quota 当前默认| R7["按 regime 静态配额<br/>FUNNEL_AI_*_TREND/ACCUM"]
        R8{"FUNNEL_DYNAMIC_POLICY"}
        R8 -->|off| R9["静态配额"]
        R8 -->|shadow| R10["静态出结果 + shadow 差异写库"]
        R8 -->|on| R11["读 signal_health/registry 动态配额"]
        R12["L2旁路 / 战略旁路 / 主线加权送审"]
        R14["外部观察 Shadow<br/>只验证不入 AI"]
        R13["飞书推送漏斗报告"]
    end

    PREP --> GATE --> L1 --> L2
    P1 --> P8
    L2 --> L2A & L2B & L2C & L2D & L2E & L2F
    L2A & L2B & L2C & L2D & L2E & L2F --> L3 --> L4
    L1 --> BYPASS
    L4 --> L5
    L4 --> POST
    BYPASS --> POST
    P8 --> POST
    L5 --> POST
```

### L4 触发信号

| 信号 | 含义 | 典型轨道 |
|------|------|----------|
| SOS | 放量突破 | Trend |
| Spring | 假跌破收回 | Accum |
| LPS | 缩量回踩 | Accum |
| EVR | 放量不跌 | Trend |
| Compression | 压缩蓄势 | 通用 |

### 外部观察名单

`external_seeds` 用于把人工关注、社区反馈或其它系统给出的股票加入同一套漏斗观察，而不是作为正式候选来源：

- 配置来源：`config/profiles/a_share_prod.yml`、`FUNNEL_EXTERNAL_SEED_SYMBOLS`、`FUNNEL_EXTRA_SYMBOLS` 或 `symbols_file`
- 默认只做 shadow 观察：记录是否通过 L1/L2、是否在 L2 后触发 L4、是否过期
- 外部观察名单固定为 shadow-only，不进入 `selected_for_ai`
- 通过 L4 的外部观察对象会额外写入 `signal_observations`，`selection_mode=external_seed_shadow`

---

## 四、Step3 AI 研报流程

```mermaid
flowchart LR
    IN["symbols_info<br/>漏斗候选 + 元数据"] --> FETCH["逐只拉 OHLCV<br/>320 日窗口"]
    FETCH --> FEAT["特征工程<br/>generate_stock_payload<br/>均线/量价切片/高光事件"]
    FEAT --> SPLIT["双轨分组<br/>Trend vs Accum"]
    SPLIT --> LLM["LLM 三阵营审判<br/>逻辑破产 / 储备营地 / 起跳板"]
    LLM --> RAG["RAG 语义防雷<br/>rag_veto 新闻否决"]
    RAG --> OUT["extract_operation_pool_codes<br/>提取起跳板代码"]
    OUT --> PUSH["飞书/企微/钉钉推送研报"]
    OUT --> MARK["mark_ai_recommendations<br/>recommendation_tracking"]
```

**LLM 配置**（workflow 默认）：

- Step3：`STEP3_LLM_PROVIDER=gemini`，fallback `efficiency`
- 输入不是原始 K 线，而是压缩后的结构特征

---

## 五、Step4 OMS 持仓决断

```mermaid
flowchart TD
    IN1["Step3 研报文本"] --> S4
    IN2["起跳板 candidate_meta"] --> S4
    IN3["Supabase portfolios<br/>USER_LIVE:user_id"] --> S4
    IN4["market_signal_daily<br/>benchmark + premarket"] --> S4
    IN5["TickFlow 持仓分时诊断"] --> S4

    S4["run_step4()"] --> IDEM{"幂等检查<br/>同日同持仓快照已跑?"}
    IDEM -->|是| SKIP["跳过"]
    IDEM -->|否| LLM["LLM 决策<br/>EXIT > TRIM > HOLD > PROBE/ATTACK"]

    LLM --> RISK{"风控门控"}
    RISK -->|CRASH / BLACK_SWAN / RISK_OFF| BLOCK_BUY["冻结买入<br/>STEP4_BUY_BLOCK_REGIMES"]
    RISK -->|NORMAL / CAUTION| ALLOW["允许按仓位上限执行"]

    ALLOW --> OMS["硬止损 -9%<br/>PROBE≤10% / ATTACK≤20%"]
    OMS --> TG["Telegram 推送决策"]
    OMS --> DB["trade_orders 写库"]
```

---

## 六、跨日反馈闭环

漏斗与 feedback 是**错峰运行**的反馈系统：漏斗先产出观察样本，feedback 盘后验收，下一轮漏斗再读取新的策略状态。详见 [`SIGNAL_FEEDBACK_LOOP.md`](SIGNAL_FEEDBACK_LOOP.md)。

```mermaid
sequenceDiagram
    participant T1 as Day N 17:17 漏斗
    participant OBS as signal_observations
    participant REC as recommendation_tracking
    participant FB as Day N 23:30 feedback
    participant HL as signal_health_daily
    participant REG as signal_registry
    participant T2 as Day N+1 17:17 漏斗

    T1->>OBS: L4 命中 + AI 起跳板标记
    T1->>REC: 形态复盘记录
    Note over T1: signal_pending 写入待确认

    FB->>OBS: 读取观察样本
    FB->>FB: 拉后续 K 线计算 1/3/5/10/20 日 outcomes
    FB->>HL: 聚合胜率/均值收益/权重
    FB->>REG: 更新信号启停状态

    T2->>HL: FUNNEL_DYNAMIC_POLICY=on 时读权重
    T2->>REG: 过滤失效信号类型
    T2->>OBS: 新一轮观察样本
```

### `FUNNEL_DYNAMIC_POLICY` 模式

| 模式 | 行为 |
|------|------|
| `off` | 默认静态 Trend / Accum 配额，不读取反馈权重 |
| `shadow` | 主流程保持静态配额，动态策略差异写入 `signal_policy_shadow_runs` |
| `on` | 正式使用 `signal_health_daily` 权重和 `signal_registry` 启停状态 |

---

## 七、并行下游任务时间线

| 时间（北京） | 工作流 | 与漏斗关系 |
|-------------|--------|-----------|
| **08:20** | `premarket_risk.yml` | **上游门控**：A50 + VIX → Step4 次日买入权限 |
| **周日-周四 17:17** | `wyckoff_funnel.yml` | **主漏斗** daily_job Step2→3→4；次日非 A 股交易日则跳过 |
| **19:25** | `review_list_replay.yml` | 下游：涨停复盘 |
| **21:10 周五** | `theme_radar.yml` | 下游：主线雷达周报（新闻增强） |
| **23:00 日–四** | `recommendation_tracking_reprice.yml` | 下游：复盘重定价 |
| **23:05** | `db_maintenance.yml` | 下游：清理过期数据 |
| **23:30** | `signal_feedback.yml` | **下游反馈**：刷新 health / registry |
| **次日 13:50** | `tail_buy_1420.yml` | **下游执行**：读 `signal_pending` 尾盘策略；pending 只观察，confirmed 才可 BUY |

---

## 八、Supabase 数据流

```mermaid
flowchart LR
    subgraph STEP2_WRITE["Step2 写入"]
        W1["market_signal_daily<br/>regime / 指数"]
        W2["theme_radar_snapshot"]
        W3["signal_pending<br/>待确认信号"]
        W4["recommendation_tracking<br/>形态复盘"]
        W12["external_seed_observations<br/>外部观察验证"]
    end

    subgraph STEP3_WRITE["Step3 写入"]
        W5["recommendation_tracking<br/>AI 起跳板标记"]
        W6["signal_observations<br/>L4 观察样本"]
    end

    subgraph STEP4_WRITE["Step4 写入"]
        W7["trade_orders<br/>买卖建议"]
    end

    subgraph FEEDBACK["23:30 反馈"]
        W8["signal_outcomes"]
        W9["signal_health_daily"]
        W10["signal_registry"]
        W11["signal_policy_shadow_runs"]
    end

    STEP2_WRITE --> FEEDBACK
    STEP3_WRITE --> FEEDBACK
    FEEDBACK -->|下一轮漏斗读取| STEP2_WRITE
```

---

## 九、数据源降级链（OHLCV）

```
TickFlow (优先, qfq 前复权)
  ↓ 失败
Tushare
  ↓ 失败
AkShare
  ↓ 失败
Baostock
  ↓ 失败
efinance
```

- 批量参数：`BATCH_SIZE=200`，`MAX_WORKERS=4`，320 交易日窗口
- 快照：`data/funnel_snapshots/`（供回测离线使用）

---

## 十、当前生产配置要点

来源：`.github/workflows/wyckoff_funnel.yml`

| 变量 | 当前值 | 作用 |
|------|--------|------|
| `FUNNEL_AI_SELECTION_MODE` | `tradeable_l4` | 只把可交易 L4 结构送入 Step3，减少裸 SOS/EVR 追高噪声 |
| `FUNNEL_AI_TOTAL_CAP` | `8` | AI 总量硬上限；战略/主题补位也受此限制 |
| `FUNNEL_DYNAMIC_POLICY` | `shadow` | 主流程用静态配额，同时记录动态策略差异 |
| `FUNNEL_AI_NEUTRAL_TREND` / `FUNNEL_AI_NEUTRAL_ACCUM` | `2` / `3` | 中性市场保留更多 Accum 槽位给 Spring/LPS/Compression |
| `FUNNEL_EXTERNAL_SEED_SYMBOLS` / `FUNNEL_EXTRA_SYMBOLS` | 空 | 临时追加外部观察名单；存在时自动启用 external seed shadow |
| `STEP4_BUY_HARD_STOP_PCT` | `8.0` | 新开仓硬止损 |
| `STEP4_REQUIRE_CONFIRMED_BUY_CANDIDATE` | `1` | Step4 新开仓只允许二次确认候选；未确认候选只观察 |
| `TAIL_BUY_CONFIRMED_ONLY_BUY` | `1` | 尾盘买入只对二次确认候选输出 BUY |
| `STEP4_BUY_BLOCK_REGIMES` | `CRASH,BLACK_SWAN,RISK_OFF` | 极寒熔断 |

---

## 相关文档

| 文档 | 内容 |
|------|------|
| [`README_STRATEGY.md`](../README_STRATEGY.md) | 策略逻辑、L1–L5 条件、AI 研报与 OMS 规则 |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | 架构、Actions 全表、Supabase 表结构 |
| [`SIGNAL_FEEDBACK_LOOP.md`](SIGNAL_FEEDBACK_LOOP.md) | 信号反馈闭环详解 |
| [`GLOSSARY.md`](../GLOSSARY.md) | 术语速查 |
