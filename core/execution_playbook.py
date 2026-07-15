"""Shared A-share execution playbook text for daily reports."""

from __future__ import annotations

from core.market_trade_mode import MarketTradeMode, resolve_market_trade_mode


def funnel_playbook_lines(regime: str | None, selected_count: int = 0) -> list[str]:
    """Top-of-funnel card: what the operator should do tomorrow."""
    mode = resolve_market_trade_mode(regime)
    lines = [
        "**【🧭 今日执行纪律】**",
        f"1. 闸门：{mode.label}（{mode.mode}）— {mode.reason}",
        f"2. 新开仓：{_new_buy_rule(mode, selected_count)}",
        "3. 只做主线：优先「主线买点候选 / 起跳板」；旁路、Accum、观察池不占主仓。",
        "4. 买入链路：漏斗候选 → Step3 审判 → 跨日确认 confirmed → 尾盘 BUY → OMS 核准。",
        "5. 持有：非主线默认 **5 日**时间止盈；主线约 **15 日**，破 MA20 或主题缩量阴跌再减。",
        "6. 止损：结构/时间优先；**-12%** 仅灾难地板，勿当日常洗盘止损。",
        "7. 读报告：先看本纪律与候选清单，再看明细；禁止新仓日不要从观察名单下单。",
        "",
    ]
    return lines


def tail_buy_playbook_lines(*, report_mode: str = "intraday") -> list[str]:
    """Tail-buy / post-close review header rules."""
    if report_mode == "post_close_review":
        return [
            "**【🧭 执行纪律】**",
            "- BUY=明日可观察买入；WATCH=继续等；SKIP=放弃。",
            "- 仅 confirmed 或盘后复核通过才进入计划；次日仍要防高开追价。",
            "- 非主线默认 5 日兑现；主线破 MA20 / 主题转弱再减。",
            "- 高开过大、破支撑、冲高回落：直接放弃，不硬接。",
            "",
        ]
    return [
        "**【🧭 执行纪律】**",
        "- BUY=今日可执行；WATCH=只观察；SKIP=不买。",
        "- RISK_ON/弱市/修复期：禁止新开仓（持仓仍可 TRIM/HOLD）。",
        "- 未 confirmed / 无支撑锚点 / 涨停无法挂单：不当作可执行买入。",
        "- 高位动能票即使 rule=BUY，也默认只观察；主线 confirmed 优先。",
        "- 持仓时间管理：非主线满5日优先时间止盈；灾难地板约 -12%。",
        "",
    ]


def oms_playbook_lines(market_view: str | None = None) -> list[str]:
    """Step4 OMS ticket header rules."""
    lines = [
        "**【🧭 执行纪律】**",
        "- 优先级：EXIT/TRIM（处理风险）> HOLD > PROBE/ATTACK（新开仓）。",
        "- 新开仓仅 APPROVED 的 PROBE/ATTACK；被拦截 NO_TRADE 不补单。",
        "- 持仓看「时间管理」：非主线 5 日、主线约 15 日；灾难止损约 -12%。",
        "- 明日开盘若超过防追高限价：放弃买入，不追。",
    ]
    view = str(market_view or "").strip()
    if view:
        lines.append(f"- 市场视图：{view}")
    lines.append("")
    return lines


def step3_playbook_lines(regime: str | None = None) -> list[str]:
    """Compact rules for AI report package header."""
    mode = resolve_market_trade_mode(regime)
    return [
        "【执行纪律】",
        f"- 闸门：{mode.label} — {_gate_short(mode)}",
        "- 只把「起跳板」当可操作；储备营地等待，逻辑破产不碰。",
        "- 主线回踩 MA5/MA10/MA20 或平台再突破优先；不追鱼尾。",
        "- 实盘仍需 confirmed + 尾盘确认；非主线默认 5 日兑现。",
        "",
    ]


def _new_buy_rule(mode: MarketTradeMode, selected_count: int) -> str:
    if not mode.allow_ai_review:
        return "禁止。只管理旧仓，不从本报告选新买入。"
    if mode.mode == "overheat_shadow":
        return "禁止正式新开；可做 AI/shadow 对照，不写推荐、不执行买入。"
    if not mode.allow_recommendation_write:
        return "仅观察复核；不写正式推荐，尾盘/人工确认前不自动开仓。"
    if selected_count <= 0:
        return "允许但今日无送审候选 → 空仓或只管旧仓，不硬找票。"
    return f"允许（约 {selected_count} 只送审）→ 等起跳板 + confirmed + 尾盘 BUY。"


def _gate_short(mode: MarketTradeMode) -> str:
    if not mode.allow_ai_review:
        return "禁止新仓"
    if not mode.allow_recommendation_write:
        return "观察买入"
    return "可执行买入（主线优先）"
