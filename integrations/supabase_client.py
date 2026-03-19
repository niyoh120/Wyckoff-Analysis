import os
import streamlit as st
from supabase import create_client, Client
from postgrest.exceptions import APIError
from core.constants import TABLE_USER_SETTINGS
from integrations.llm_client import OPENAI_COMPATIBLE_BASE_URLS


def reset_user_settings_state() -> None:
    """
    重置当前会话中的用户敏感配置，防止跨账号残留。
    """
    st.session_state.feishu_webhook = ""
    st.session_state.wecom_webhook = ""
    st.session_state.dingtalk_webhook = ""
    st.session_state.gemini_api_key = ""
    st.session_state.tushare_token = ""
    st.session_state.gemini_model = "gemini-3.1-flash-lite-preview"
    st.session_state.tg_bot_token = ""
    st.session_state.tg_chat_id = ""

    # 多厂商大模型配置（按需使用）
    st.session_state.openai_api_key = ""
    st.session_state.openai_model = ""
    st.session_state.openai_base_url = OPENAI_COMPATIBLE_BASE_URLS.get("openai", "")
    st.session_state.zhipu_api_key = ""
    st.session_state.zhipu_model = ""
    st.session_state.zhipu_base_url = OPENAI_COMPATIBLE_BASE_URLS.get("zhipu", "")
    st.session_state.minimax_api_key = ""
    st.session_state.minimax_model = ""
    st.session_state.minimax_base_url = OPENAI_COMPATIBLE_BASE_URLS.get("minimax", "")
    st.session_state.deepseek_api_key = ""
    st.session_state.deepseek_model = ""
    st.session_state.deepseek_base_url = OPENAI_COMPATIBLE_BASE_URLS.get("deepseek", "")
    st.session_state.qwen_api_key = ""
    st.session_state.qwen_model = ""
    st.session_state.qwen_base_url = OPENAI_COMPATIBLE_BASE_URLS.get("qwen", "")


def _get_supabase_client_base() -> Client:
    # 优先尝试从 os.getenv 读取（本地 .env 文件）
    # 其次尝试从 st.secrets 读取（Streamlit Cloud 部署环境）
    url = os.getenv("SUPABASE_URL")
    # ⚠️  此处必须填 anon key（公开权限），不得填 service_role key。
    # 若误填 service_role key，未登录用户将绕过 RLS，可读写所有用户数据。
    key = os.getenv("SUPABASE_KEY")

    if not url or not key:
        # 如果 os.getenv 没取到，再试 st.secrets
        try:
            url = st.secrets["SUPABASE_URL"]
            key = st.secrets["SUPABASE_KEY"]
        except (FileNotFoundError, KeyError):
            pass

    if not url or not key:
        raise ValueError(
            "Missing Supabase credentials. Please set SUPABASE_URL and SUPABASE_KEY in .env or secrets."
        )

    return create_client(url, key)


def _apply_user_session(supabase: Client) -> None:
    """
    将当前用户会话绑定到 Supabase 客户端（用于 RLS）
    """
    access_token = st.session_state.get("access_token")
    refresh_token = st.session_state.get("refresh_token")

    if access_token and refresh_token:
        try:
            supabase.auth.set_session(access_token, refresh_token)
        except Exception:
            pass

    if access_token:
        supabase.postgrest.auth(access_token)
    else:
        # 回退到 anon key（未登录场景）。
        # ⚠️  此处 supabase_key 应为 anon key；若误配 service_role key 会绕过 RLS。
        supabase.postgrest.auth(supabase.supabase_key)


def get_supabase_client() -> Client:
    if "supabase_client_base" not in st.session_state:
        st.session_state.supabase_client_base = _get_supabase_client_base()
    supabase = st.session_state.supabase_client_base
    _apply_user_session(supabase)
    return supabase


def load_user_settings(user_id: str):
    """从 Supabase 加载用户配置到 st.session_state"""
    reset_user_settings_state()
    if not user_id:
        return False
    try:
        supabase = get_supabase_client()
        response = (
            supabase.table(TABLE_USER_SETTINGS)
            .select("*")
            .eq("user_id", user_id)
            .execute()
        )

        if response.data and len(response.data) > 0:
            settings = response.data[0]
            # 通知类
            st.session_state.feishu_webhook = settings.get("feishu_webhook") or ""
            st.session_state.wecom_webhook = settings.get("wecom_webhook") or ""
            st.session_state.dingtalk_webhook = settings.get("dingtalk_webhook") or ""

            # 大模型配置
            st.session_state.gemini_api_key = settings.get("gemini_api_key") or ""
            st.session_state.gemini_model = (
                settings.get("gemini_model") or "gemini-3.1-flash-lite-preview"
            )
            st.session_state.openai_api_key = settings.get("openai_api_key") or ""
            st.session_state.openai_model = settings.get("openai_model") or ""
            st.session_state.openai_base_url = (
                settings.get("openai_base_url")
                or OPENAI_COMPATIBLE_BASE_URLS.get("openai", "")
            )
            st.session_state.zhipu_api_key = settings.get("zhipu_api_key") or ""
            st.session_state.zhipu_model = settings.get("zhipu_model") or ""
            st.session_state.zhipu_base_url = (
                settings.get("zhipu_base_url")
                or OPENAI_COMPATIBLE_BASE_URLS.get("zhipu", "")
            )
            st.session_state.minimax_api_key = settings.get("minimax_api_key") or ""
            st.session_state.minimax_model = settings.get("minimax_model") or ""
            st.session_state.minimax_base_url = (
                settings.get("minimax_base_url")
                or OPENAI_COMPATIBLE_BASE_URLS.get("minimax", "")
            )
            st.session_state.deepseek_api_key = settings.get("deepseek_api_key") or ""
            st.session_state.deepseek_model = settings.get("deepseek_model") or ""
            st.session_state.deepseek_base_url = (
                settings.get("deepseek_base_url")
                or OPENAI_COMPATIBLE_BASE_URLS.get("deepseek", "")
            )
            st.session_state.qwen_api_key = settings.get("qwen_api_key") or ""
            st.session_state.qwen_model = settings.get("qwen_model") or ""
            st.session_state.qwen_base_url = (
                settings.get("qwen_base_url")
                or OPENAI_COMPATIBLE_BASE_URLS.get("qwen", "")
            )

            # 其它
            st.session_state.tushare_token = settings.get("tushare_token") or ""
            st.session_state.tg_bot_token = settings.get("tg_bot_token") or ""
            st.session_state.tg_chat_id = settings.get("tg_chat_id") or ""
            return True
    except APIError as e:
        print(f"Supabase API Error in load_user_settings: {e.code} - {e.message}")
    except Exception as e:
        print(f"Unexpected error in load_user_settings: {e}")
    return False


def save_user_settings(user_id: str, settings: dict):
    """保存用户配置到 Supabase"""
    try:
        supabase = get_supabase_client()
        data = {"user_id": user_id, **settings}
        # upsert: 存在则更新，不存在则插入
        supabase.table(TABLE_USER_SETTINGS).upsert(data).execute()
        return True
    except APIError as e:
        print(f"Supabase API Error in save_user_settings: {e.code} - {e.message}")
        return False
    except Exception as e:
        print(f"Unexpected error in save_user_settings: {e}")
        return False
