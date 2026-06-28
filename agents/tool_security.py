from __future__ import annotations

import ipaddress
import pathlib
import re
import shlex
import socket
from typing import Any
from urllib.parse import urlparse

SENSITIVE_KEY_RE = re.compile(
    r"(api[_-]?key|access[_-]?token|refresh[_-]?token|token|password|passwd|secret|credential|authorization|cookie|session)",
    re.IGNORECASE,
)
SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|token|password|passwd|secret|authorization|cookie)\b"
    r"\s*[:=]\s*([\"']?)[^\s\"',;]+"
)
BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{12,}")
COMMON_SECRET_VALUE_RE = re.compile(r"\b(?:sk|ak|pk|ghp|gho|github_pat|glpat|xoxb|xoxp|AIza)[A-Za-z0-9_\-]{12,}\b")
SAFE_WEB_CONTENT_TYPE_PREFIXES = (
    "application/json",
    "application/xml",
    "application/xhtml+xml",
    "text/",
)
_PROXY_FAKE_IP_NETWORKS = (ipaddress.ip_network("198.18.0.0/15"),)

_BLOCKED_PATH_PARTS = {
    ".ssh",
    ".aws",
    ".azure",
    ".config/gcloud",
    ".gnupg",
    ".kube",
    ".docker",
    ".npm",
}
_BLOCKED_FILE_NAMES = {
    ".env",
    ".env.local",
    ".env.production",
    ".netrc",
    ".npmrc",
    ".pypirc",
    "id_rsa",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
}
_ALLOWED_WYCKOFF_SUBDIRS = {"tool-results", "scratchpad", "exports", "reports"}
_BLOCKED_SYSTEM_ROOTS = (
    pathlib.Path("/bin"),
    pathlib.Path("/etc"),
    pathlib.Path("/Library"),
    pathlib.Path("/private/etc"),
    pathlib.Path("/sbin"),
    pathlib.Path("/System"),
    pathlib.Path("/usr"),
    pathlib.Path("/var"),
)
_BLOCKED_COMMANDS = {
    "bash",
    "chflags",
    "chmod",
    "chown",
    "curl",
    "dd",
    "ftp",
    "env",
    "kill",
    "launchctl",
    "mkfs",
    "nc",
    "ncat",
    "osascript",
    "pkill",
    "printenv",
    "rm",
    "rmdir",
    "rsync",
    "scp",
    "sh",
    "shred",
    "ssh",
    "su",
    "sudo",
    "wget",
    "zsh",
}
_INLINE_CODE_COMMANDS = {"python", "python3", "node", "ruby", "perl", "php"}
_SHELL_META_RE = re.compile(r"[\n\r;&|<>`]|(?<!\\)\$\(")
_SAFE_WRITE_SUFFIXES = {
    ".csv",
    ".html",
    ".json",
    ".jsonl",
    ".log",
    ".md",
    ".txt",
    ".yaml",
    ".yml",
}


def security_error(message: str) -> dict:
    return {"error": f"安全拦截: {message}"}


def redact_sensitive_text(text: str) -> str:
    if not text:
        return text
    redacted = SECRET_ASSIGNMENT_RE.sub(lambda m: f"{m.group(1)}={m.group(2)}***REDACTED***", text)
    redacted = BEARER_RE.sub("Bearer ***REDACTED***", redacted)
    return COMMON_SECRET_VALUE_RE.sub("***REDACTED***", redacted)


def redact_sensitive_columns(df: Any) -> Any:
    try:
        out = df.copy()
        for col in out.columns:
            if SENSITIVE_KEY_RE.search(str(col)):
                out[col] = "***REDACTED***"
        return out
    except Exception:
        return df


def _path_parts_lower(path: pathlib.Path) -> list[str]:
    return [part.lower() for part in path.parts]


def _is_allowed_wyckoff_path(parts: list[str]) -> bool:
    if ".wyckoff" not in parts:
        return False
    idx = parts.index(".wyckoff")
    return len(parts) > idx + 1 and parts[idx + 1] in _ALLOWED_WYCKOFF_SUBDIRS


def _is_under_path(path: pathlib.Path, root: pathlib.Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def validate_agent_path(path: str, *, for_write: bool = False) -> pathlib.Path | dict:
    if not path or not str(path).strip():
        return security_error("文件路径不能为空")

    try:
        p = pathlib.Path(path).expanduser().resolve()
    except Exception as e:
        return security_error(f"文件路径无效: {e}")

    parts = _path_parts_lower(p)
    joined = "/".join(parts)
    name = p.name.lower()
    allowed_wyckoff_path = _is_allowed_wyckoff_path(parts)

    if any(_is_under_path(p, root) for root in _BLOCKED_SYSTEM_ROOTS):
        return security_error("禁止访问系统目录")
    if _is_under_path(p, pathlib.Path.home().expanduser() / "Library"):
        return security_error("禁止访问用户 Library 配置目录")
    if ".wyckoff" in parts and not allowed_wyckoff_path:
        return security_error("禁止读取或写入 Wyckoff 凭据、会话和配置目录")
    if any(part in parts for part in _BLOCKED_PATH_PARTS) or any(part in joined for part in _BLOCKED_PATH_PARTS):
        return security_error("禁止访问凭据、密钥或云配置目录")
    hidden_parts = [part for part in parts if part.startswith(".") and part not in {".", "..", ".wyckoff"}]
    if hidden_parts and not allowed_wyckoff_path:
        return security_error("禁止访问隐藏文件或隐藏目录")
    if name in _BLOCKED_FILE_NAMES or name.startswith(".env"):
        return security_error("禁止访问环境变量或密钥文件")
    if SENSITIVE_KEY_RE.search(name):
        return security_error("文件名疑似包含凭据或会话数据")
    if for_write and p.suffix.lower() not in _SAFE_WRITE_SUFFIXES:
        allowed = ", ".join(sorted(_SAFE_WRITE_SUFFIXES))
        return security_error(f"只允许写入文本/报告类文件: {allowed}")
    return p


def validate_agent_command(command: str) -> list[str] | dict:
    raw = str(command or "").strip()
    if not raw:
        return security_error("命令不能为空")
    if len(raw) > 500:
        return security_error("命令过长，请拆成更小的只读操作")
    if _SHELL_META_RE.search(raw):
        return security_error("禁止使用 shell 控制符、管道、重定向、命令替换或多条命令")

    try:
        args = shlex.split(raw)
    except ValueError as e:
        return security_error(f"命令解析失败: {e}")
    if not args:
        return security_error("命令不能为空")

    executable = pathlib.Path(args[0]).name.lower()
    if executable in _BLOCKED_COMMANDS:
        return security_error(f"禁止通过 Agent 执行高风险命令: {executable}")
    if executable in _INLINE_CODE_COMMANDS and any(arg in {"-c", "-e"} for arg in args[1:]):
        return security_error("禁止通过 Agent 执行内联代码")
    for arg in args[1:]:
        lowered = arg.lower()
        touches_wyckoff_config = ".wyckoff" in lowered and not any(
            f".wyckoff/{subdir}" in lowered for subdir in _ALLOWED_WYCKOFF_SUBDIRS
        )
        if SENSITIVE_KEY_RE.search(arg) or ".ssh" in lowered or ".env" in lowered or touches_wyckoff_config:
            return security_error("命令参数疑似访问凭据、会话或密钥")
    return args


def validate_public_http_url(url: str) -> str | dict:
    raw = str(url or "").strip()
    if not raw:
        return security_error("URL 不能为空")

    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"}:
        return security_error("只允许抓取 http/https URL")
    if parsed.username or parsed.password:
        return security_error("URL 中禁止携带用户名或密码")
    if not parsed.hostname:
        return security_error("URL 缺少主机名")
    if parsed.port and parsed.port not in {80, 443}:
        return security_error("禁止抓取非标准端口，避免访问内网服务")

    host = parsed.hostname.strip().lower().rstrip(".")
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        return security_error("禁止抓取本机或本地域名")

    try:
        infos = socket.getaddrinfo(
            host, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM
        )
    except socket.gaierror:
        return security_error("URL 主机无法解析")

    host_is_ip_literal = _parse_ip(host) is not None
    for info in infos:
        ip_result = _validate_public_ip(info[4][0], allow_proxy_fake_ip=not host_is_ip_literal)
        if ip_result:
            return ip_result
    return raw


def _parse_ip(ip_text: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(ip_text)
    except ValueError:
        return None


def _validate_public_ip(ip_text: str, *, allow_proxy_fake_ip: bool = False) -> dict | None:
    ip = _parse_ip(ip_text)
    if ip is None:
        return security_error("URL 解析到无效地址")
    if allow_proxy_fake_ip and any(ip in network for network in _PROXY_FAKE_IP_NETWORKS):
        return None
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
        return security_error("禁止抓取内网、本机、链路本地或保留地址")
    return None
