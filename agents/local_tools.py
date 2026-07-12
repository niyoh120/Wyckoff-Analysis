from __future__ import annotations

import json
import os
import re
import subprocess
from typing import Any
from urllib.parse import urljoin

from agents.tool_security import (
    SAFE_WEB_CONTENT_TYPE_PREFIXES,
    redact_sensitive_columns,
    redact_sensitive_text,
    security_error,
    validate_agent_command,
    validate_agent_path,
    validate_public_http_url,
)

MAX_AGENT_FILE_BYTES = 50 * 1024 * 1024
MAX_AGENT_TEXT_WRITE_BYTES = 2 * 1024 * 1024
MAX_AGENT_WEB_BYTES = 1024 * 1024
MAX_AGENT_WEB_REDIRECTS = 5


def exec_command(command: str, timeout: int = 30, cwd: str = "", tool_context: Any = None) -> dict:
    args = validate_agent_command(command)
    if isinstance(args, dict):
        return args
    workdir = _command_cwd(cwd)
    if isinstance(workdir, dict):
        return workdir

    timeout = max(1, min(int(timeout), 120))
    try:
        result = subprocess.run(
            args,
            shell=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=workdir,
        )
        stdout = redact_sensitive_text(result.stdout)
        stderr = redact_sensitive_text(result.stderr)
        return {
            "cwd": str(workdir),
            "stdout": stdout[:8000] + ("...(截断)" if len(stdout) > 8000 else ""),
            "stderr": stderr[:2000] + ("...(截断)" if len(stderr) > 2000 else ""),
            "returncode": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"error": f"命令超时（{timeout}s）", "returncode": -1}
    except Exception as e:
        return {"error": str(e)}


def _command_cwd(cwd: str) -> str | dict:
    if not str(cwd or "").strip():
        return os.path.expanduser("~")
    resolved = validate_agent_path(cwd, for_write=False)
    if isinstance(resolved, dict):
        return resolved
    if not resolved.exists():
        return security_error(f"工作目录不存在: {resolved}")
    if not resolved.is_dir():
        return security_error(f"工作目录不是目录: {resolved}")
    return str(resolved)


def read_file(path: str, encoding: str = "utf-8", tool_context: Any = None) -> dict:
    resolved = validate_agent_path(path, for_write=False)
    if isinstance(resolved, dict):
        return resolved
    if not resolved.exists():
        return {"error": f"文件不存在: {resolved}"}
    if not resolved.is_file():
        return {"error": f"不是文件: {resolved}"}
    size = resolved.stat().st_size
    if size > MAX_AGENT_FILE_BYTES:
        return {"error": f"文件过大 ({size / 1024 / 1024:.1f}MB)，上限 50MB"}

    try:
        if resolved.suffix.lower() in {".csv", ".xls", ".xlsx"}:
            return _read_table_preview(resolved, encoding, size)
        if resolved.suffix.lower() == ".json":
            return _read_json_preview(resolved, encoding, size)
        content = redact_sensitive_text(resolved.read_text(encoding=encoding))
        return {
            "path": str(resolved),
            "size": size,
            "content": content[:10000] + ("...(截断)" if len(content) > 10000 else ""),
        }
    except Exception as e:
        return {"error": f"读取失败: {e}"}


def _read_table_preview(path, encoding: str, size: int) -> dict:
    import pandas as pd

    df = (
        pd.read_csv(path, encoding=encoding, nrows=50)
        if path.suffix.lower() == ".csv"
        else pd.read_excel(path, nrows=50)
    )
    preview = redact_sensitive_columns(df).to_markdown(index=False)
    return {"path": str(path), "size": size, "rows_total": "≤50(预览)", "content": redact_sensitive_text(preview)}


def _read_json_preview(path, encoding: str, size: int) -> dict:
    text = path.read_text(encoding=encoding)[:10000]
    try:
        content = json.dumps(json.loads(text), ensure_ascii=False, indent=2)[:10000]
    except json.JSONDecodeError:
        content = text
    return {"path": str(path), "size": size, "content": redact_sensitive_text(content)}


def write_file(path: str, content: str, encoding: str = "utf-8", tool_context: Any = None) -> dict:
    resolved = validate_agent_path(path, for_write=True)
    if isinstance(resolved, dict):
        return resolved
    try:
        content_bytes = str(content).encode(encoding)
    except LookupError:
        return {"error": f"写入失败: 不支持的编码 {encoding}"}
    if len(content_bytes) > MAX_AGENT_TEXT_WRITE_BYTES:
        return security_error("写入内容过大，上限 2MB")
    try:
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(content, encoding=encoding)
        return {"path": str(resolved), "size": resolved.stat().st_size}
    except Exception as e:
        return {"error": f"写入失败: {e}"}


def web_fetch(url: str, tool_context: Any = None) -> dict:
    import requests

    safe_url = validate_public_http_url(url)
    if isinstance(safe_url, dict):
        return safe_url

    try:
        resp, final_url = _get_public_response(requests, safe_url)
        if isinstance(resp, dict):
            return resp
        resp.raise_for_status()
        ctype = resp.headers.get("content-type", "").lower()
        if ctype and not any(ctype.startswith(prefix) for prefix in SAFE_WEB_CONTENT_TYPE_PREFIXES):
            return security_error(f"拒绝抓取非文本内容: {ctype}")

        body = _read_response_body(resp)
        if isinstance(body, dict):
            return body
        text = _extract_response_text(body, ctype)
        return {"url": final_url, "status": resp.status_code, "content": redact_sensitive_text(text)}
    except Exception as e:
        return {"error": f"抓取失败: {e}"}


def _get_public_response(requests_module, initial_url: str):
    url = initial_url
    for _ in range(MAX_AGENT_WEB_REDIRECTS + 1):
        checked = validate_public_http_url(url)
        if isinstance(checked, dict):
            return checked, url
        resp = requests_module.get(
            checked,
            timeout=(3, 15),
            headers={"User-Agent": "Wyckoff-Agent/1.0"},
            stream=True,
            allow_redirects=False,
        )
        if resp.status_code not in {301, 302, 303, 307, 308}:
            return resp, checked
        location = resp.headers.get("location", "").strip()
        resp.close()
        if not location:
            return security_error("重定向响应缺少 Location"), checked
        url = urljoin(checked, location)
    return security_error(f"网页重定向超过 {MAX_AGENT_WEB_REDIRECTS} 次"), url


def _read_response_body(resp) -> str | dict:
    chunks: list[bytes] = []
    total = 0
    for chunk in resp.iter_content(chunk_size=65536):
        if not chunk:
            continue
        chunks.append(chunk)
        total += len(chunk)
        if total > MAX_AGENT_WEB_BYTES:
            return security_error("网页响应过大，上限 1MB")
    return b"".join(chunks).decode(resp.encoding or "utf-8", errors="replace")


def _extract_response_text(body: str, ctype: str) -> str:
    if "json" in ctype:
        return body[:8000]
    if "html" not in ctype:
        return body[:8000]
    text = re.sub(r"<script[^>]*>.*?</script>", "", body, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()[:8000]
