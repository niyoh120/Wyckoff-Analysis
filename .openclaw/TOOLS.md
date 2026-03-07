# TOOLS.md - 策略武器库档案

当前分析环境的本地基础设施笔记，作为 AI 副参谋的快捷入口。

## 架构双轨定位 (Engineering Strategy)

- **后台生产线 (GitHub Actions 定时任务)**：负责承载核心的 `每日选股`、`批量研报` 和 `风控OMS` 逻辑。不受 Web 端并发与超时限制，专注于每天精准、稳定、重度地计算与筛选。
- **前端 Web (Streamlit Ui)**：主要作为一种低成本的数据赋能看板，供主理人及访客提取原始历史行情、查看量化分析案例。仅做轻量级的查询展现与表单配置。

## 核心管线脚本

- **量化漏斗引擎**：`core/wyckoff_engine.py` -> 掌控 Layer 1（剥离垃圾）到 Layer 4（Trigger）的数学判决权。
- **每日选股流**：`scripts/wyckoff_funnel.py` -> 执行全市场扫描与大盘水温反馈控制。
- **AI 批量研报**：`scripts/step3_batch_report.py` -> 双轨并行提取上下文，交付给大模型裁定（逻辑破产 / 储备营地 / 处于起跳板）。
- **风控巡逻兵**：`scripts/premarket_risk_job.py` -> 盘前拦截宏观黑天鹅。
- **OMS 终极决断**：`scripts/step4_rebalancer.py` -> 组合校验与签名字段去重防重传。
- **参数扫描实验室**：`scripts/param_sensitivity.py` -> 网格化暴力寻优。

## 关键集成与架构机制

- **持久化平台**: `integrations/supabase_portfolio.py` 托管用户状态。
- **新闻舆情防雷**: `integrations/rag_veto.py` 控制剔除严重负面消息污染的标的。
- **不可变回放快照**: 数据提取落盘至 `data/funnel_snapshots` 目录，便于分离网络问题和策略逻辑对比。

保持敬畏，我们用这些工具是在市场上真金白银博弈。
