# Wyckoff Web 基建迭代计划（历史路线图）

> 更新于 2026-06-28 | 当前状态：React Web 已承担主要交互入口；读盘室已迁到 Hono Worker API；Supabase 仍是 Auth、用户配置、持仓、推荐、信号反馈和策略观察的事实数据库。本文保留迁移路线与后续方向，不作为当前架构事实源。当前事实请看 [`ARCHITECTURE.md`](ARCHITECTURE.md)。

## 当前架构

```
React SPA (Cloudflare Pages)              wyckoff-analysis.pages.dev
  ├─ @ai-sdk/react useChat + UIMessage parts
  ├─ Supabase JS SDK (Auth + DB)
  │
  │  POST /api/chat
  ↓
Pages Functions / Hono Worker             同域 /api/*
  ├─ /api/chat                            读用户配置、执行工具、返回 UIMessage stream
  ├─ /api/chat/config                     检查读盘室模型配置
  └─ /api/llm-proxy/*                     兼容代理，服务行情/LLM 直连能力
  ↓
LLM Providers (外部)
  ├─ 1Route (https://api.1route.dev/v1)
  ├─ DeepSeek (https://api.deepseek.com/v1)
  ├─ OpenAI / Gemini / 智谱 / 通义千问 / 火山引擎
  ↓
Supabase (Auth + PostgreSQL + RLS)        yfyivczvmorpqdyehfmn.supabase.co
```

已完成：
- React + Vite + shadcn/ui 前端，部署到 Cloudflare Pages
- Supabase Auth 登录/注册
- MarketBar 大盘水温组件（读 market_signal_daily）
- Git push 自动触发构建部署
- **Pages Functions /api/llm-proxy** — 解决 LLM 跨域 + 密钥不暴露
- **读盘室 AI Agent** — Hono Worker + Vercel AI SDK + 13 个工具（搜索/持仓/大盘/诊断/选股/研报/策略/尾盘/盘中）
- **UIMessage 化** — 前端使用 `useChat` / `DefaultChatTransport` 渲染消息 parts、工具结果和审批状态
- **工具审批** — `execute_portfolio_update` 走协议层确认，不再只依赖提示词约束
- **compatibility 模式** — 兼容 1Route/DeepSeek/通义千问等第三方 OpenAI 接口
- **Gemini SSE 归一化** — 兼容 Gemini OpenAI-compatible 工具流差异，避免前端丢工具调用结果
- **读盘室模型快捷切换** — 无需跳转设置页

## 历史目标架构

下面是 2026-05 的迁移设想，不代表当前已完成状态。当前路线是先减少 Supabase 中最重的行情缓存和大对象压力，核心业务表继续留在 Supabase，直到 D1 / KV / R2 的 RLS、同步和后台任务能力经过完整验证。

```
React SPA (Cloudflare Pages)
  │ useChat() / fetch()
  ↓
Cloudflare Worker (Hono)
  ├─ /api/chat          → SSE streaming (Vercel AI SDK + tool calling)
  ├─ /api/portfolio/*   → D1 CRUD
  ├─ /api/settings/*    → KV read/write
  ├─ /api/market/*      → TickFlow API proxy + R2 缓存
  └─ /api/export/*      → TickFlow + R2 缓存
  ↓
Cloudflare D1 (候选主数据库)  ←  仅在验证完成后才可能替代部分 Supabase PostgreSQL 表
Cloudflare KV (配置缓存)
Cloudflare R2 (文件/K线缓存)
Supabase Auth (仅保留登录认证)
```

## Cloudflare 存储服务对比

| 服务 | 类型 | 适合场景 | 免费额度 | 本项目用途 |
|------|------|----------|----------|-----------|
| **D1** | SQLite 关系数据库 | 结构化数据、SQL 查询 | 5GB 存储，500 万次读/天，10 万次写/天 | 持仓、复盘记录、聊天历史、funnel 结果 |
| **KV** | 全局键值存储 | 配置、缓存、高频读低频写 | 10 万次读/天，1000 次写/天，1GB 存储 | 用户设置、LLM 配置、session 缓存 |
| **R2** | 对象存储 (S3 兼容) | 文件、大对象、静态资源 | 10GB 存储，100 万次读/月，10 万次写/月 | K 线 OHLCV 缓存、导出 CSV、研报 PDF |
| **Workers** | 边缘计算 | API 路由、代理、业务逻辑 | 10 万次请求/天，10ms CPU | Hono API、Agent SSE、TickFlow 代理 |
| **Pages** | 静态网站托管 | SPA、SSG | 无限带宽，500 次构建/月 | React 前端（已部署） |

## 迁移路线

### Phase 1 — 前端上线 ✅

- [x] React + Vite + shadcn/ui 搭建
- [x] Supabase Auth 接入
- [x] MarketBar 组件
- [x] Cloudflare Pages 部署

### Phase 2 — Worker API + 数据页面

目标：把读盘室长链路后端化；数据 CRUD 仍以 Supabase/RLS 直连为主，Worker 只承接需要服务端执行的能力。

- [x] Hono Worker 搭建 + wrangler 配置
- [x] Auth 中间件（验证 Supabase JWT）
- [x] `/api/chat` 与 `/api/chat/config`
- [ ] Portfolio / Settings Worker CRUD 正式接管（当前 Web 页面仍以 Supabase/RLS 直连为主）
- [x] Wyckoff Pattern Replay / 跟踪页（白名单可见，读取 Supabase 复盘表）

### Phase 3 — Cloudflare 存储迁移

目标：将高频数据从 Supabase 迁移到 Cloudflare 存储，降低 Supabase 用量

**D1 迁移（结构化数据）：**
- [ ] 创建 D1 数据库，定义 schema
- [ ] 迁移 `portfolio_holdings` 表 → D1
- [ ] 迁移 `chat_messages` 表 → D1（最大的存储消耗）
- [ ] 迁移 `funnel_results` 表 → D1
- [ ] 迁移 `recommendation_tracking` 表 → D1
- [ ] Worker API 改为读写 D1

**KV 迁移（配置类）：**
- [ ] 创建 KV namespace
- [ ] 迁移 `user_settings` → KV（key: `user:{uid}:settings`）
- [ ] LLM 配置缓存 → KV
- [ ] Session/token 缓存 → KV

**R2 缓存（大文件）：**
- [ ] 创建 R2 bucket
- [ ] K 线 OHLCV 数据缓存（TickFlow 回源 → R2 → 前端）
- [ ] 导出 CSV 暂存
- [ ] CLI cron 每日预热热门股票 K 线到 R2

### Phase 4 — Agent 对话

目标：Web 端完整 Agent 体验

- [x] `/api/chat` SSE endpoint（Vercel AI SDK + tool calling）
- [x] 13 个读盘室工具：search_stock、view_portfolio、market_overview、market_history、query_recommendations、query_tail_buy、plan/execute portfolio update、analyze_stock、screen_stocks、generate_ai_report、generate_strategy_decision、intraday_analysis
- [x] Chat UI（useChat hook + streaming + tool call 展示）
- [x] analyze_stock 工具（TickFlow OHLCV + Wyckoff 判定）
- [x] K 线图组件（Lightweight Charts）
- [x] generate_ai_report / generate_strategy_decision 工具
- [x] 消息排队、Gemini SSE 归一化、工具审批与结构化工具卡片

### Phase 5 — 优化上线

- [ ] 自定义域名
- [ ] Supabase 降级：仅保留 Auth（PostgreSQL 可关闭或降到最低用量）
- [ ] 性能优化：R2 缓存命中率、D1 查询索引、KV 读取延迟
- [ ] 监控：Workers Analytics + 错误告警

## 迁移后 Supabase 用量预估（历史假设）

| 服务 | 迁移前 | 迁移后 |
|------|--------|--------|
| Auth | 登录认证 | 登录认证（保留） |
| Database | 全部业务表 | 理论上仅 Auth 相关表；当前未完成 |
| Bandwidth | 高（前端直连） | 理论上极低；当前仍需按实际 Supabase 表读写评估 |

## 成本估算

| 阶段 | 月成本 |
|------|--------|
| 当前（Supabase 全量） | 接近免费额度上限 |
| Phase 3 完成后 | 历史假设：Cloudflare 免费层 + Supabase Auth 免费；当前不应按 ¥0 预算 |
| 规模期（1000+ 用户） | ~$5/月（D1 付费层 $0.75/GB，按需） |
