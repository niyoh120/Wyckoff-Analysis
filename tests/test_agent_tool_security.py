from __future__ import annotations

from agents.local_tools import exec_command, read_file, web_fetch, write_file


def test_exec_command_allows_simple_read_only_command():
    result = exec_command("echo hello")

    assert result["returncode"] == 0
    assert "hello" in result["stdout"]


def test_exec_command_blocks_shell_control_operators():
    result = exec_command("echo hello; cat ~/.wyckoff/config.json")

    assert result["error"].startswith("安全拦截")
    assert "shell 控制符" in result["error"]


def test_exec_command_blocks_destructive_command():
    result = exec_command("rm -rf /tmp/wyckoff-agent-security-test")

    assert result["error"].startswith("安全拦截")
    assert "高风险命令" in result["error"]


def test_exec_command_blocks_inline_code():
    result = exec_command("python -c 'print(123)'")

    assert result["error"].startswith("安全拦截")
    assert "内联代码" in result["error"]


def test_exec_command_blocks_environment_dump():
    result = exec_command("printenv")

    assert result["error"].startswith("安全拦截")
    assert "高风险命令" in result["error"]


def test_exec_command_blocks_wyckoff_config_path():
    result = exec_command("ls ~/.wyckoff/config.json")

    assert result["error"].startswith("安全拦截")
    assert "凭据" in result["error"] or "会话" in result["error"]


def test_read_file_blocks_sensitive_path_name(tmp_path):
    target = tmp_path / "api_key.txt"
    target.write_text("api_key=secret", encoding="utf-8")

    result = read_file(str(target))

    assert result["error"].startswith("安全拦截")
    assert "凭据" in result["error"]


def test_read_file_redacts_secret_assignments(tmp_path):
    target = tmp_path / "notes.txt"
    target.write_text("normal=1\napi_key=secret-value\n", encoding="utf-8")

    result = read_file(str(target))

    assert "normal=1" in result["content"]
    assert "secret-value" not in result["content"]
    assert "***REDACTED***" in result["content"]


def test_read_file_blocks_system_file():
    result = read_file("/etc/passwd")

    assert result["error"].startswith("安全拦截")
    assert "系统目录" in result["error"]


def test_read_file_blocks_hidden_directory(tmp_path):
    hidden = tmp_path / ".cache" / "notes.txt"
    hidden.parent.mkdir()
    hidden.write_text("not a secret", encoding="utf-8")

    result = read_file(str(hidden))

    assert result["error"].startswith("安全拦截")
    assert "隐藏" in result["error"]


def test_write_file_allows_report_file(tmp_path):
    target = tmp_path / "report.md"

    result = write_file(str(target), "# report")

    assert result["path"] == str(target)
    assert target.read_text(encoding="utf-8") == "# report"


def test_write_file_blocks_executable_suffix(tmp_path):
    target = tmp_path / "run.py"

    result = write_file(str(target), "print('hi')")

    assert result["error"].startswith("安全拦截")
    assert not target.exists()


def test_web_fetch_blocks_localhost():
    result = web_fetch("http://127.0.0.1/")

    assert result["error"].startswith("安全拦截")
    assert "内网" in result["error"] or "本机" in result["error"]


def test_web_fetch_blocks_non_http_scheme():
    result = web_fetch("file:///etc/passwd")

    assert result["error"].startswith("安全拦截")
    assert "http/https" in result["error"]
