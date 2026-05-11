"""威科夫形态复盘页面。"""

from datetime import date, datetime

import pandas as pd
import streamlit as st

from app.layout import setup_page
from app.navigation import show_right_nav
from app.ui_helpers import show_page_loading
from integrations.supabase_client import get_supabase_client
from integrations.supabase_recommendation import load_recommendation_tracking

setup_page(page_title="形态复盘", page_icon="🎯")

RECOMMENDATION_KEEP_DATES = 30
AVG_WINDOWS = (5, 10, 15, 20, 25, 30)


def _format_pct(val):
    if val is None or pd.isna(val):
        return "-"
    return f"{val:+.2f}%"


def _latest_recommend_dates(df: pd.DataFrame, limit: int) -> list[int]:
    dates = pd.to_numeric(df.get("recommend_date"), errors="coerce").dropna().astype(int)
    return sorted({d for d in dates.tolist() if d > 0}, reverse=True)[:limit]


content_col = show_right_nav()

with content_col:
    st.title("🎯 威科夫形态复盘")
    st.markdown("每日定时任务自动入选威科夫形态股票，并复盘其后续走势表现。数据在每日定时任务后自动刷新。")
    st.info(
        "此页仅展示复盘表中最新 30 个复盘交易日的数据；这 30 个日期按数据库实际存在的入选日计算，不按连续自然日补齐。"
    )

    # 1. 加载数据
    loading = show_page_loading(title="思考中...", subtitle="从数据库加载复盘历史")
    try:
        raw_data = load_recommendation_tracking(limit=2000, client=get_supabase_client())
    finally:
        loading.empty()

    if not raw_data:
        st.info("目前暂无形态复盘数据，请等待下一次定时任务运行。")
        st.stop()

    # 2. 转换数据为 DataFrame 并处理展示逻辑
    df = pd.DataFrame(raw_data)
    if "recommend_date" not in df.columns:
        st.error("形态复盘数据缺少 recommend_date 字段，请检查 recommendation_tracking 表结构或 RLS 权限。")
        st.caption("返回字段：" + ", ".join(str(c) for c in df.columns.tolist()))
        st.stop()
    if "code" not in df.columns:
        st.error("形态复盘数据缺少 code 字段，请检查 recommendation_tracking 表结构或 RLS 权限。")
        st.caption("返回字段：" + ", ".join(str(c) for c in df.columns.tolist()))
        st.stop()
    if "name" not in df.columns:
        df["name"] = ""
    if "recommend_reason" not in df.columns:
        df["recommend_reason"] = ""
    if "is_ai_recommended" not in df.columns:
        df["is_ai_recommended"] = False
    if "funnel_score" not in df.columns:
        df["funnel_score"] = pd.NA
    df["is_ai_recommended"] = (
        df["is_ai_recommended"].apply(lambda x: str(x).strip().lower() in {"1", "true", "t", "yes", "y"}).astype(bool)
    )
    if "rag_vetoed" not in df.columns:
        df["rag_vetoed"] = False
    df["rag_vetoed"] = (
        df["rag_vetoed"].apply(lambda x: str(x).strip().lower() in {"1", "true", "t", "yes", "y"}).astype(bool)
    )
    df["funnel_score"] = pd.to_numeric(df["funnel_score"], errors="coerce")
    df["initial_price"] = pd.to_numeric(df.get("initial_price"), errors="coerce")
    df["current_price"] = pd.to_numeric(df.get("current_price"), errors="coerce")
    df["change_pct"] = pd.to_numeric(df.get("change_pct"), errors="coerce")
    if "recommend_count" not in df.columns:
        df["recommend_count"] = 1
    df["recommend_count"] = pd.to_numeric(df.get("recommend_count"), errors="coerce").fillna(1).astype(int)
    df["recommend_date"] = pd.to_numeric(df.get("recommend_date"), errors="coerce").fillna(0).astype(int)
    latest_dates = _latest_recommend_dates(df, RECOMMENDATION_KEEP_DATES)
    if latest_dates:
        df = df[df["recommend_date"].isin(latest_dates)].copy()
    else:
        st.info("目前暂无有效入选日期，请等待下一次定时任务运行。")
        st.stop()

    st.markdown("### 🔎 复盘交易日窗口")
    selected_window = st.selectbox(
        "统计与列表窗口",
        options=AVG_WINDOWS,
        index=len(AVG_WINDOWS) - 1,
        format_func=lambda v: f"近{v}个复盘交易日",
        help="按复盘表中实际存在的入选日期倒序取样，不按连续自然日补齐。",
    )
    active_dates = latest_dates[:selected_window]
    df = df[df["recommend_date"].isin(active_dates)].copy()
    stats_df = df.copy()

    # 格式化日期 (INT YYYYMMDD -> YYYY-MM-DD str)
    def _parse_date(v: int):
        s = str(int(v))
        if len(s) == 8 and s.isdigit():
            try:
                return datetime.strptime(s, "%Y%m%d").date()
            except Exception:
                return None
        return None

    def _format_date(v: int) -> str:
        dt = _parse_date(v)
        if dt is not None:
            return dt.strftime("%Y-%m-%d")
        return "-"

    today = date.today()
    df["recommend_date_dt"] = df["recommend_date"].apply(_parse_date)
    df["recommend_date_str"] = df["recommend_date"].apply(_format_date)

    # 格式化代码 (INT -> 000001 str)
    df["code"] = pd.to_numeric(df.get("code"), errors="coerce").fillna(0).astype(int)
    df["display_code"] = df["code"].apply(lambda x: f"{int(x):06d}")

    # ── 同一只股票去重：按 code 聚合，只保留最新一条，推荐次数取最大值 ──
    df = df.sort_values("recommend_date", ascending=False)
    agg_map = {
        "name": "first",
        "recommend_date": "first",
        "recommend_date_dt": "first",
        "recommend_date_str": "first",
        "initial_price": "first",
        "current_price": "first",
        "change_pct": "first",
        "is_ai_recommended": "any",  # 任意一次被 AI 推荐过就标 True
        "rag_vetoed": "any",
        "recommend_count": "max",  # 取最大推荐次数
        "recommend_reason": "first",
        "funnel_score": "first",
        "display_code": "first",
    }
    # 只聚合存在的列
    agg_map = {k: v for k, v in agg_map.items() if k in df.columns}
    df = df.groupby("code", as_index=False).agg(agg_map)

    df["days_since_recommend"] = df["recommend_date_dt"].apply(lambda d: (today - d).days if d is not None else pd.NA)

    # 3. 统计指标 (KPIs)
    st.markdown("### 📊 表现摘要")
    st.caption(f"当前窗口覆盖 {len(active_dates)} 个复盘交易日，{len(stats_df)} 条复盘记录。")
    col1, col2, col3, col4, col5 = st.columns(5)
    active_df = df[~df["rag_vetoed"]]
    avg_change = active_df["change_pct"].mean()
    max_change = active_df["change_pct"].max()
    min_change = active_df["change_pct"].min()
    total_recommend_events = int(df["recommend_count"].sum())

    col1.metric("覆盖股票数", f"{len(df)} 支")
    col2.metric(f"近{selected_window}个复盘交易日平均涨幅", _format_pct(avg_change))
    col3.metric("最高涨幅", _format_pct(max_change))
    col4.metric("最大跌幅", _format_pct(min_change))
    col5.metric("总入选次数", f"{total_recommend_events} 次")

    st.divider()

    # 4. 搜索与排序增强
    st.markdown("### 🔍 筛选与搜索")
    search_col, ai_col, sort_col, order_col = st.columns([2, 1, 1, 1])

    with search_col:
        search_query = st.text_input("搜索代码或名字", placeholder="输入 601318 或 中国平安...", key="rec_search")

    with ai_col:
        only_ai = st.checkbox("只看AI入选", value=False, key="rec_only_ai")

    with sort_col:
        sort_by = st.selectbox(
            "排序",
            options=["默认（涨幅→入选次数→AI→日期→分值→现价）", "入选日期", "涨跌幅", "分值", "代码"],
            index=0,
        )
    with order_col:
        sort_order = st.radio("顺序", options=["降序", "升序"], horizontal=True)

    # 筛选
    filtered_df = df.copy()
    if search_query:
        filtered_df = filtered_df[
            (filtered_df["display_code"].str.contains(search_query, na=False))
            | (filtered_df["name"].astype(str).str.contains(search_query, na=False))
        ]
    if only_ai:
        filtered_df = filtered_df[filtered_df["is_ai_recommended"]]

    # 排序：默认多级（涨幅高→低，同涨幅推荐次数高→低，同则 AI 在上，同则日期新→旧，同则分值高→低，同则现价高→低）
    if sort_by == "默认（涨幅→入选次数→AI→日期→分值→现价）":
        filtered_df = filtered_df.sort_values(
            by=[
                "change_pct",
                "recommend_count",
                "is_ai_recommended",
                "recommend_date",
                "funnel_score",
                "current_price",
            ],
            ascending=[False, False, False, False, False, False],
            na_position="last",
        )
    else:
        sort_map = {
            "入选日期": "recommend_date",
            "涨跌幅": "change_pct",
            "分值": "funnel_score",
            "代码": "code",
        }
        filtered_df = filtered_df.sort_values(
            by=sort_map[sort_by],
            ascending=(sort_order == "升序"),
            na_position="last",
        )

    # 5. 结果展示
    # 构建最终展示的列表
    display_df = filtered_df[
        [
            "display_code",
            "name",
            "change_pct",
            "initial_price",
            "current_price",
            "is_ai_recommended",
            "rag_vetoed",
            "recommend_count",
            "days_since_recommend",
            "recommend_date_str",
            "recommend_reason",
            "funnel_score",
        ]
    ].copy()
    display_df["is_ai_recommended"] = display_df["is_ai_recommended"].map(lambda x: "是" if bool(x) else "否")
    display_df["rag_vetoed"] = display_df["rag_vetoed"].map(lambda x: "已剔除" if bool(x) else "")

    display_df.columns = [
        "代码",
        "名称",
        "累计涨跌幅",
        "加入价",
        "当前价",
        "AI入选",
        "RAG防雷",
        "入选次数",
        "入选天数",
        "入选日期",
        "入选原因",
        "复盘分值",
    ]

    # 使用 dataframe 渲染，增加一些样式建议
    st.dataframe(
        display_df.style.format(
            {
                "入选天数": lambda v: "-" if pd.isna(v) else f"{int(v)}",
                "复盘分值": lambda v: "-" if pd.isna(v) else f"{float(v):.2f}",
                "加入价": "{:.2f}",
                "当前价": "{:.2f}",
                "累计涨跌幅": "{:+.2f}%",
            }
        )
        .map(
            lambda v: (
                "color: red;"
                if isinstance(v, str) and "+" in v
                else ("color: green;" if isinstance(v, str) and "-" in v else "")
            ),
            subset=["累计涨跌幅"],
        )
        .map(lambda v: "color: #16a34a; font-weight: 700;" if v == "是" else "color: #6b7280;", subset=["AI入选"])
        .map(lambda v: "color: #dc2626; font-weight: 700;" if v == "已剔除" else "", subset=["RAG防雷"]),
        use_container_width=True,
        hide_index=True,
        height=600,
    )

    if st.button("🔄 手动刷新数据"):
        st.rerun()
