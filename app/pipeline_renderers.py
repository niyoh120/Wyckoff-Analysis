# -*- coding: utf-8 -*-
"""
Pipeline 阶段进度渲染器 — 供 pages/AIAnalysis.py 的完整管线模式使用。

将 OrchestratorAgent 的 stages checkpoint 数据渲染为
st.status 阶段面板，提供实时进度可视化。
"""
from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

# ---------------------------------------------------------------------------
# 阶段元数据：(agent_name, 中文标签, emoji, 描述)
# ---------------------------------------------------------------------------
STAGE_META: list[tuple[str, str, str, str]] = [
    ("screener", "漏斗筛选", "🔬", "4 层 Wyckoff 漏斗，从全市场筛出候选股"),
    ("market_context", "大盘环境", "🌡️", "指数水温、MA 趋势、市场宽度"),
    ("analyst", "AI 研报", "🤖", "LLM 三阵营分析（进攻 / 起跳 / 观察）"),
    ("strategist", "持仓策略", "📊", "OMS 仓位决策 + 风控止损"),
    ("notifier", "通知汇总", "📨", "飞书 / 企微 / 钉钉 / Telegram"),
]

_STAGE_NAMES = [s[0] for s in STAGE_META]


def _find_stage_checkpoint(
    stages: list[dict[str, Any]],
    agent_name: str,
) -> dict[str, Any] | None:
    """从 stages list 中找到指定 agent 的 checkpoint。"""
    for s in stages:
        if s.get("agent_name") == agent_name:
            return s
    return None


def render_pipeline_progress(
    stages: list[dict[str, Any]],
    current_stage: str,
    current_stage_status: str,
    is_running: bool,
) -> None:
    """
    渲染 5 阶段进度面板。

    Args:
        stages: 已完成的 checkpoint dict 列表。
        current_stage: 当前正在运行的 agent name。
        current_stage_status: "running" | "completed" | "failed" 等。
        is_running: pipeline 是否仍在运行。
    """
    completed_names = {s.get("agent_name") for s in stages}

    for agent_name, label, emoji, description in STAGE_META:
        checkpoint = _find_stage_checkpoint(stages, agent_name)

        if checkpoint:
            # 已完成
            status_val = checkpoint.get("status", "completed")
            duration_ms = checkpoint.get("duration_ms", 0)
            duration_s = duration_ms / 1000.0 if duration_ms else 0
            error = checkpoint.get("error")
            retries = checkpoint.get("retries", 0)

            if status_val == "completed":
                state = "complete"
                suffix = f"{duration_s:.1f}s" + (f" (重试 {retries} 次)" if retries else "")
                header = f"{emoji} {label}  —  {suffix}"
            else:
                state = "error"
                header = f"{emoji} {label}  —  失败"

            with st.status(header, state=state):
                if error:
                    st.error(error)
                elif status_val == "completed":
                    st.caption(description)
                    if duration_s > 0:
                        st.caption(f"耗时 {duration_s:.1f} 秒")

        elif is_running and agent_name == current_stage and current_stage_status == "running":
            # 当前正在运行
            with st.status(f"{emoji} {label}  —  运行中...", state="running"):
                st.caption(description)

        elif is_running and agent_name not in completed_names:
            # 等待中
            st.markdown(
                f"<div style='padding: 8px 16px; margin: 4px 0; "
                f"border-radius: 8px; background: #f0f2f6; color: #888;'>"
                f"{emoji} {label}  —  等待中</div>",
                unsafe_allow_html=True,
            )
        else:
            # Pipeline 已结束但此阶段没有 checkpoint（被跳过）
            st.markdown(
                f"<div style='padding: 8px 16px; margin: 4px 0; "
                f"border-radius: 8px; background: #f0f2f6; color: #aaa;'>"
                f"{emoji} {label}  —  已跳过</div>",
                unsafe_allow_html=True,
            )


def render_pipeline_summary(result: dict[str, Any]) -> None:
    """渲染管线完成后的汇总结果区域。"""
    stages = result.get("stages", [])
    duration_ms = result.get("duration_ms", 0)
    ok = result.get("ok", False)
    status = result.get("status", "")

    # 总耗时
    if duration_ms:
        total_s = duration_ms / 1000.0
        col1, col2, col3 = st.columns(3)
        col1.metric("管线状态", "成功" if ok else "部分完成")
        col2.metric("总耗时", f"{total_s:.1f}s")
        col3.metric("阶段数", f"{len(stages)}/5")

    # 漏斗结果
    symbols_for_report = result.get("symbols_for_report", [])
    if symbols_for_report:
        with st.expander(f"🔬 漏斗候选（{len(symbols_for_report)} 只）", expanded=True):
            rows = []
            for item in symbols_for_report:
                if not isinstance(item, dict):
                    continue
                rows.append({
                    "代码": str(item.get("code", "")),
                    "名称": str(item.get("name", "")),
                    "行业": str(item.get("industry", "")),
                    "轨道": str(item.get("track", "")),
                    "阶段": str(item.get("stage", "")),
                    "标签": str(item.get("tag", "")),
                    "评分": round(float(item.get("score", 0) or 0), 3),
                })
            if rows:
                st.dataframe(
                    pd.DataFrame(rows),
                    use_container_width=True,
                    hide_index=True,
                )

    # 大盘环境
    benchmark = result.get("benchmark_context", {})
    if benchmark:
        with st.expander("🌡️ 大盘环境"):
            regime = str(benchmark.get("regime", "")).upper()
            close_val = benchmark.get("close")
            ma50 = benchmark.get("ma50")
            ma200 = benchmark.get("ma200")

            parts = []
            if regime:
                parts.append(f"**Regime**: {regime}")
            if close_val:
                parts.append(f"上证收盘: {close_val}")
            if ma50 and ma200:
                parts.append(f"MA50: {ma50:.2f} / MA200: {ma200:.2f}")
            if parts:
                st.markdown(" · ".join(parts))

            st.json(benchmark)

    # AI 研报
    report_text = str(result.get("report_text", "") or "").strip()
    if report_text:
        with st.expander("🤖 AI 研报", expanded=True):
            st.markdown(report_text)

    # 策略决策
    decisions = result.get("strategy_decisions", [])
    if decisions:
        with st.expander(f"📊 策略决策（{len(decisions)} 条）"):
            for d in decisions:
                if isinstance(d, dict):
                    code = d.get("code", "")
                    action = d.get("action", "")
                    reason = d.get("reason", "")
                    st.markdown(f"- **{code}** → `{action}` {reason}")

    # 原始 stages JSON
    if stages:
        with st.expander("阶段详情 (JSON)"):
            st.json(stages)
