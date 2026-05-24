"""
Supabase 客户端工厂 — CLI / 脚本 / Web 通用。

所有需要 Supabase 客户端的代码应从此模块获取，而不是各自 create_client。
- 脚本/定时任务：使用 create_admin_client()（service_role key，绕过 RLS）
- CLI：无 .env，自动回退到 cli/auth 内置的 anon key
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from supabase import Client

logger = logging.getLogger(__name__)


def _resolve_credentials() -> tuple[str, str]:
    """解析 Supabase URL 和 Key，统一回退链：环境变量 → 内置 anon key。"""
    url = os.getenv("SUPABASE_URL", "").strip()
    key = os.getenv("SUPABASE_KEY", "").strip()
    if url and key:
        return url, key
    # 内置 anon key（CLI / 无 .env 场景）
    from core.constants import SUPABASE_ANON_KEY, SUPABASE_ANON_URL

    url = url or SUPABASE_ANON_URL
    key = key or SUPABASE_ANON_KEY
    if url and key:
        return url, key
    return url, key


def create_admin_client() -> Client:
    """Service-role 客户端（写库用，不经过 RLS）。

    优先读 SUPABASE_SERVICE_ROLE_KEY，回退到通用凭据链。
    """
    from supabase import create_client

    url = os.getenv("SUPABASE_URL", "").strip()
    service_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if url and service_key:
        return create_client(url, service_key)
    # 无 service_role key 时走通用链（CLI 场景用 anon key）
    url, key = _resolve_credentials()
    if not url or not key:
        raise ValueError("SUPABASE_URL / SUPABASE_KEY 未配置")
    return create_client(url, key)


def create_anon_client() -> Client:
    """Anon-key 客户端（RLS 保护）。"""
    from supabase import create_client

    url, key = _resolve_credentials()
    if not url or not key:
        raise ValueError("Missing Supabase credentials. Please set SUPABASE_URL and SUPABASE_KEY.")
    return create_client(url, key)


def create_user_client(access_token: str, refresh_token: str = "") -> Client:
    """用用户 JWT 创建客户端（通过 RLS）。

    set_session 会消耗 refresh_token 并返回新 token pair，
    调用者应通过 get_session_tokens() 获取刷新后的 token 并回写。
    """
    from supabase import create_client

    url, key = _resolve_credentials()
    if not url or not key:
        raise ValueError("SUPABASE_URL / SUPABASE_KEY 未配置")
    client = create_client(url, key)
    if refresh_token:
        resp = client.auth.set_session(access_token, refresh_token)
        # set_session 返回新 token pair，用新的 access_token 做 postgrest auth
        new_at = getattr(resp, "access_token", None) or (
            resp.session.access_token if hasattr(resp, "session") and resp.session else None
        )
        if new_at:
            access_token = new_at
    client.postgrest.auth(access_token)
    return client


def get_session_tokens(client: Client) -> tuple[str, str]:
    """从 client 中提取当前有效的 access_token 和 refresh_token。"""
    try:
        session = client.auth.get_session()
        if session:
            return session.access_token or "", session.refresh_token or ""
    except Exception:
        logger.debug("failed to retrieve session tokens", exc_info=True)
    return "", ""


def close_client(client: Client) -> None:
    """关闭 Supabase client 底层的 httpx 连接，避免 CLOSE_WAIT 泄漏。"""
    try:
        rest = getattr(client, "_postgrest", None) or getattr(client, "postgrest", None)
        if rest:
            session = getattr(rest, "session", None) or getattr(rest, "_session", None)
            if session and hasattr(session, "aclose"):
                import asyncio

                try:
                    asyncio.get_event_loop().run_until_complete(session.aclose())
                except Exception:
                    pass
            elif session and hasattr(session, "close"):
                session.close()
    except Exception:
        logger.debug("close_client: postgrest session close failed", exc_info=True)
    try:
        auth = getattr(client, "auth", None)
        if auth:
            http = getattr(auth, "_http_client", None) or getattr(auth, "http_client", None)
            if http and hasattr(http, "close"):
                http.close()
    except Exception:
        logger.debug("close_client: auth http close failed", exc_info=True)


def is_admin_configured() -> bool:
    """检查是否存在显式 Supabase 凭据。

    说明：
    - 这里用于判断“是否完成业务级配置”，不应把内置 anon 凭据视为“已配置”。
    - 因此不走 _resolve_credentials()（该函数会回退到内置 anon）。
    """
    url = os.getenv("SUPABASE_URL", "").strip()
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip() or os.getenv("SUPABASE_KEY", "").strip()
    if url and key:
        return True
    return False
