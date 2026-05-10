"""Supabase tail_buy_history 表读写。"""

from __future__ import annotations

import os
from typing import Any

from core.constants import TABLE_TAIL_BUY_HISTORY
from integrations.supabase_base import create_admin_client as _admin
from integrations.supabase_base import is_admin_configured as _configured


def _get_user_id() -> str:
    return os.getenv("SUPABASE_USER_ID", "").strip()


def save_tail_buy_to_supabase(rows: list[dict], user_id: str = "") -> int:
    """写入 BUY 记录到 Supabase，upsert on (code, run_date, user_id)。"""
    if not _configured() or not rows:
        return 0
    user_id = user_id.strip() or _get_user_id()
    if not user_id:
        print("[tail_buy] user_id not provided and SUPABASE_USER_ID not set, skip")
        return 0
    payload = [
        {
            "code": r["code"],
            "name": r.get("name", ""),
            "run_date": r["run_date"],
            "signal_date": r.get("signal_date", ""),
            "signal_type": r.get("signal_type", ""),
            "final_decision": r.get("final_decision", "BUY"),
            "rule_score": float(r.get("rule_score", 0)),
            "priority_score": float(r.get("priority_score", 0)),
            "rule_reasons": r.get("rule_reasons", ""),
            "llm_decision": r.get("llm_decision", ""),
            "llm_reason": r.get("llm_reason", ""),
            "user_id": user_id,
        }
        for r in rows
    ]
    try:
        client = _admin()
        client.table(TABLE_TAIL_BUY_HISTORY).upsert(
            payload, on_conflict="code,run_date,user_id"
        ).execute()
        return len(payload)
    except Exception as e:
        print(f"[tail_buy] supabase write failed: {e}")
        return 0


def load_tail_buy_from_supabase(limit: int = 100, user_id: str = "") -> list[dict[str, Any]]:
    """读取最近 N 条尾盘买入记录。"""
    if not _configured():
        return []
    user_id = user_id.strip() or _get_user_id()
    if not user_id:
        print("[tail_buy] user_id not provided and SUPABASE_USER_ID not set, skip read")
        return []
    try:
        client = _admin()
        q = client.table(TABLE_TAIL_BUY_HISTORY).select("*").eq("user_id", user_id)
        resp = q.order("run_date", desc=True).limit(limit).execute()
        return resp.data or []
    except Exception as e:
        print(f"[tail_buy] supabase read failed: {e}")
        return []
