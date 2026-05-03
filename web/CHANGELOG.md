# Web App 更新日志

## v1.0.0 (2026-05-03)

React Web App 首版上线，部署到 Cloudflare Pages。

### 核心功能

- **读盘室**: AI Agent 对话，支持 10 个量化工具自动编排，流式输出 + 工具调用可视化
- **读盘室模型切换**: 顶部快捷切换已配置的模型，无需跳转设置页
- **漏斗选股**: 每日全市场漏斗筛选结果，按交易日浏览
- **推荐跟踪**: 1000+ 推荐股票实时涨跌追踪，平均涨幅/最佳/最大回撤统计
- **持仓管理**: 持仓总览 + 增删操作
- **尾盘记录**: 尾盘买入策略历史记录
- **单股分析**: AI 威科夫深度诊断
- **数据导出**: OHLCV 增强版 / 原始数据下载
- **大盘水温**: 上证/A50/VIX + 市场情绪标签
- **设置**: 多 LLM 供应商配置（1Route/Gemini/OpenAI/DeepSeek/智谱/通义千问/火山引擎）

### 基础设施

- React 19 + Vite 6 + TypeScript
- Tailwind CSS v4 + shadcn/ui
- Supabase Auth + PostgreSQL
- Cloudflare Pages 自动部署（Git push → build → deploy）
- Pages Functions 边缘代理（/api/llm-proxy）
- DeepSeek R1 reasoning_content 回传兼容
- 第三方 LLM 供应商 compatibility 模式

### 链接

- Web App: https://wyckoff-analysis.pages.dev/home
- 项目主页: https://youngcan-wang.github.io/wyckoff-homepage/
