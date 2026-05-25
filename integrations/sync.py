"""
Supabase → SQLite 同步引擎。

CLI 启动时后台拉取 Supabase 数据到本地 SQLite，保证离线可用。
"""

from __future__ import annotations

import logging
import os
import threading

logger = logging.getLogger(__name__)


def _get_admin_client():
    from integrations.supabase_base import create_admin_client, is_admin_configured

    if not is_admin_configured():
        return None
    return create_admin_client()


def sync_recommendations(client=None) -> int:
    from core.constants import TABLE_RECOMMENDATION_TRACKING
    from integrations.local_db import save_recommendations, update_sync_meta

    sb = client or _get_admin_client()
    if sb is None:
        return 0
    resp = sb.table(TABLE_RECOMMENDATION_TRACKING).select("*").order("recommend_date", desc=True).limit(200).execute()
    rows = resp.data or []
    n = save_recommendations(rows)
    update_sync_meta("recommendation_tracking", n)
    return n


def sync_signals(client=None) -> int:
    from core.constants import TABLE_SIGNAL_PENDING
    from integrations.local_db import save_signals, update_sync_meta

    sb = client or _get_admin_client()
    if sb is None:
        return 0
    resp = sb.table(TABLE_SIGNAL_PENDING).select("*").order("signal_date", desc=True).limit(200).execute()
    rows = resp.data or []
    n = save_signals(rows)
    update_sync_meta("signal_pending", n)
    return n


def sync_market_signals(client=None) -> int:
    from core.constants import TABLE_MARKET_SIGNAL_DAILY
    from integrations.local_db import save_market_signal, update_sync_meta

    sb = client or _get_admin_client()
    if sb is None:
        return 0
    resp = sb.table(TABLE_MARKET_SIGNAL_DAILY).select("*").order("trade_date", desc=True).limit(30).execute()
    rows = resp.data or []
    for r in rows:
        td = str(r.get("trade_date", "")).strip()
        if td:
            save_market_signal(td, r)
    update_sync_meta("market_signal_daily", len(rows))
    return len(rows)


def sync_portfolio(portfolio_id: str = "USER_LIVE", client=None) -> int:
    from integrations.local_db import save_portfolio, update_sync_meta
    from integrations.supabase_portfolio import load_portfolio_state

    sb = client or _get_admin_client()
    if sb is None:
        return 0
    state = load_portfolio_state(portfolio_id, client=sb)
    if not state:
        return 0
    positions = state.get("positions", [])
    save_portfolio(
        portfolio_id,
        float(state.get("free_cash", 0) or 0),
        [
            {
                "code": p.get("code", ""),
                "name": p.get("name", ""),
                "shares": p.get("shares", 0),
                "cost_price": p.get("cost", p.get("cost_price", 0)),
                "stop_loss": p.get("stop_loss"),
            }
            for p in positions
        ],
    )
    update_sync_meta("portfolio", 1 + len(positions))
    return 1 + len(positions)


def _tail_buy_local_row(row: dict) -> dict:
    return {
        "code": str(row.get("code", "")),
        "name": row.get("name", ""),
        "run_date": str(row.get("run_date", "")),
        "signal_date": row.get("signal_date", ""),
        "signal_type": row.get("signal_type", ""),
        "status": row.get("status", ""),
        "final_decision": row.get("final_decision", "BUY"),
        "rule_decision": row.get("rule_decision", ""),
        "rule_score": float(row.get("rule_score", 0)),
        "priority_score": float(row.get("priority_score", 0)),
        "rule_reasons": row.get("rule_reasons", ""),
        "llm_decision": row.get("llm_decision", ""),
        "llm_reason": row.get("llm_reason", ""),
        "llm_confidence": row.get("llm_confidence"),
        "llm_model_used": row.get("llm_model_used", ""),
        "initial_price": row.get("initial_price", 0),
        "current_price": row.get("current_price", 0),
        "change_pct": row.get("change_pct", 0),
        "price_updated_at": row.get("price_updated_at", ""),
        "last_close": row.get("last_close", 0),
        "vwap": row.get("vwap", 0),
        "dist_vwap_pct": row.get("dist_vwap_pct", 0),
        "close_pos": row.get("close_pos", 0),
        "day_ret_pct": row.get("day_ret_pct", 0),
        "last30_ret_pct": row.get("last30_ret_pct", 0),
        "last15_ret_pct": row.get("last15_ret_pct", 0),
        "tail30_volume_share": row.get("tail30_volume_share", 0),
        "drop_from_high_pct": row.get("drop_from_high_pct", 0),
        "fetch_error": row.get("fetch_error", ""),
        "features_json": row.get("features_json", ""),
    }


def sync_tail_buy(client=None, user_id: str = "") -> int:
    from core.constants import TABLE_TAIL_BUY_HISTORY
    from integrations.local_db import save_tail_buy_results, update_sync_meta

    user_id = user_id.strip() or os.getenv("SUPABASE_USER_ID", "").strip()
    if not user_id:
        logger.warning("sync_tail_buy skipped: user_id not provided and SUPABASE_USER_ID not set")
        return 0
    sb = client or _get_admin_client()
    if sb is None:
        return 0
    resp = (
        sb.table(TABLE_TAIL_BUY_HISTORY)
        .select("*")
        .eq("user_id", user_id)
        .order("run_date", desc=True)
        .limit(200)
        .execute()
    )
    rows = resp.data or []
    persistable = [_tail_buy_local_row(r) for r in rows]
    n = save_tail_buy_results(persistable)
    update_sync_meta("tail_buy_history", n)
    return n


def sync_all() -> dict[str, int]:
    """同步所有表。返回 {table_name: row_count}。"""
    from integrations.local_db import needs_sync

    result: dict[str, int] = {}
    sb = _get_admin_client()
    if sb is None:
        logger.debug("sync_all: Supabase admin not configured, skipping")
        return result
    for table, fn, max_age in [
        ("recommendation_tracking", sync_recommendations, 4),
        ("signal_pending", sync_signals, 4),
        ("market_signal_daily", sync_market_signals, 6),
        ("portfolio", sync_portfolio, 2),
        ("tail_buy_history", sync_tail_buy, 4),
    ]:
        if not needs_sync(table, max_age_hours=max_age):
            continue
        try:
            result[table] = fn(client=sb)
        except Exception as e:
            logger.warning("sync %s failed: %s", table, e)
            result[table] = -1
    return result


def sync_all_background() -> None:
    """在后台线程中执行 sync_all，不阻塞主线程。"""

    def _run():
        try:
            from integrations.local_db import init_db

            init_db()
            result = sync_all()
            if result:
                parts = [f"{k}={v}" for k, v in result.items() if v > 0]
                if parts:
                    logger.info("sync done: %s", ", ".join(parts))
        except Exception as e:
            logger.debug("background sync failed: %s", e)

    t = threading.Thread(target=_run, daemon=True, name="wyckoff-sync")
    t.start()
