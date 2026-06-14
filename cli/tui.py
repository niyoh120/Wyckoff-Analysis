"""
威科夫终端读盘室 — Textual TUI。

全屏布局：上方可滚动聊天区 + 下方固定输入框。
"""

from __future__ import annotations

import contextlib
import json
import logging
import re
import threading
import time
import uuid
from collections import deque
from typing import Any

from rich.highlighter import Highlighter
from rich.markdown import Markdown
from rich.markup import escape
from rich.text import Text
from textual import events, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList, RichLog, Static
from textual.widgets.option_list import Option

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 禁用 kitty keyboard protocol（与 macOS 中文输入法冲突）
# CSI-u 序列格式: \x1b[ keycode ; modifiers ; text_codepoints u
# 中文 IME 产生的序列含冒号分隔的 Unicode codepoints，textual 无法解析
# 策略：输出侧阻止启用 kitty protocol + 输入侧将 CSI-u 解码为纯文本
# ---------------------------------------------------------------------------
_KITTY_ENABLE = "\x1b[>1u"
_KITTY_DISABLE = "\x1b[<u"
_CSI_U_IME_RE = re.compile(r"\x1b\[\d+(?::\d+)*;;([\d:]+)u")


def _decode_csi_u(m: re.Match[str]) -> str:
    text_field = m.group(1)
    try:
        return "".join(chr(int(cp)) for cp in text_field.split(":") if cp)
    except (ValueError, OverflowError):
        return m.group(0)


def _make_csi_u_input_thread(driver_self) -> None:
    """替换 run_input_thread：将 CSI-u 序列解码为纯文本后再交给 XTermParser。"""
    import os
    import selectors
    from codecs import getincrementaldecoder

    from textual._loop import loop_last
    from textual._xterm_parser import XTermParser

    selector = selectors.SelectSelector()
    selector.register(driver_self.fileno, selectors.EVENT_READ)
    fileno = driver_self.fileno
    EVENT_READ = selectors.EVENT_READ

    parser = XTermParser(driver_self._debug)
    feed = parser.feed
    tick = parser.tick
    utf8_decoder = getincrementaldecoder("utf-8")().decode

    def process_selector_events(selector_events, final=False):
        for last, (_selector_key, mask) in loop_last(selector_events):
            if mask & EVENT_READ:
                raw = os.read(fileno, 1024 * 4)
                unicode_data = utf8_decoder(raw, final=final and last)
                if not unicode_data:
                    break
                if "\x1b[" in unicode_data and "u" in unicode_data:
                    unicode_data = _CSI_U_IME_RE.sub(_decode_csi_u, unicode_data)
                if unicode_data:
                    for event in feed(unicode_data):
                        driver_self.process_message(event)
        for event in tick():
            driver_self.process_message(event)

    try:
        while not driver_self.exit_event.is_set():
            process_selector_events(selector.select(0.1))
        selector.unregister(driver_self.fileno)
        process_selector_events(selector.select(0.1), final=True)
    finally:
        selector.close()
        try:
            for _event in feed(""):
                pass
        except Exception:
            pass


def _patch_driver_no_kitty() -> None:
    from textual.drivers.linux_driver import LinuxDriver

    _orig_write = LinuxDriver.write

    def _filtered_write(self, data: str) -> None:
        if _KITTY_ENABLE in data or _KITTY_DISABLE in data:
            data = data.replace(_KITTY_ENABLE, "").replace(_KITTY_DISABLE, "")
            if not data:
                return
        _orig_write(self, data)

    LinuxDriver.write = _filtered_write
    LinuxDriver.run_input_thread = _make_csi_u_input_thread


_patch_driver_no_kitty()

# ---------------------------------------------------------------------------
# Widget
# ---------------------------------------------------------------------------
from cli.runtime import AgentCancelled
from cli.scratchpad import AgentScratchpad
from cli.workflows.dispatch import build_turn_runtime
from core.prompts import with_current_time


def _pop_lines(log_widget, n: int) -> None:
    """从 RichLog 底部移除 n 行 strips。"""
    from textual.geometry import Size

    if n > 0 and len(log_widget.lines) >= n:
        del log_widget.lines[-n:]
        log_widget.virtual_size = Size(log_widget._widest_line_width, len(log_widget.lines))
        log_widget.refresh()


def _get_agent_logger() -> logging.Logger:
    agent_log = logging.getLogger("wyckoff.agent")
    agent_log.setLevel(logging.DEBUG)
    if not agent_log.handlers:
        try:
            from core.constants import LOCAL_DB_PATH

            log_path = LOCAL_DB_PATH.parent / "agent.log"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            fh = logging.FileHandler(str(log_path), encoding="utf-8")
            fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
            agent_log.addHandler(fh)
            agent_log.propagate = False
        except Exception:
            logger.debug("agent log file handler setup failed", exc_info=True)
    return agent_log


def _write_counted(log_widget, renderable) -> int:
    """写入 RichLog，并返回实际新增的 visual strips 数。"""
    before = len(log_widget.lines)
    log_widget.write(renderable)
    return max(0, len(log_widget.lines) - before)


def _replace_streamed_response(log_widget, strip_count: int, final_text: str) -> int:
    _pop_lines(log_widget, strip_count)
    return _write_counted(log_widget, Markdown(final_text))


def _display_final_response(
    log_widget,
    final_text: str,
    *,
    streaming_started: bool,
    stream_separator_strips: int,
    stream_text_strips: int,
    write,
    call_from_thread,
) -> bool:
    if not final_text:
        return False
    if streaming_started:
        strip_count = stream_separator_strips + stream_text_strips
        call_from_thread(_replace_streamed_response, log_widget, strip_count, final_text)
    else:
        write(Text.from_markup("  [dim]───[/dim]"))
        write(Markdown(final_text))
    return True


def _build_thinking_preview(text: str) -> Text | None:
    preview = text.strip().replace("\n", " ")
    if len(preview) > 80:
        preview = preview[:80] + "…"
    if not preview:
        return None
    return Text.from_markup(f"  [italic magenta]💭 {preview}[/italic magenta]  [dim]({len(text)} 字)[/dim]")


class ChatLog(RichLog):
    DEFAULT_CSS = """
    ChatLog {
        background: $surface;
        scrollbar-size: 1 1;
    }
    """


class StatusBar(Static):
    DEFAULT_CSS = """
    StatusBar {
        dock: top;
        height: 1;
        background: $primary-background;
        color: $text-muted;
        padding: 0 1;
    }
    """


class _PasteHighlighter(Highlighter):
    def highlight(self, text: Text) -> None:
        m = re.match(r"^\[Pasted Text: \d+ lines\]$", text.plain)
        if m:
            text.stylize("bold magenta", m.start(), m.end())


class ChatInput(Input):
    """支持多行粘贴折叠显示的输入框。"""

    _pasted_text: str | None = None

    def on_paste(self, event: events.Paste) -> None:
        lines = event.text.splitlines()
        if len(lines) <= 1:
            return
        self._pasted_text = event.text
        self.value = f"[Pasted Text: {len(lines)} lines]"
        event.prevent_default()
        event.stop()

    def on_input_changed(self, event: Input.Changed) -> None:
        if self._pasted_text is None:
            return
        expected = f"[Pasted Text: {len(self._pasted_text.splitlines())} lines]"
        if event.value != expected:
            self._pasted_text = None

    def consume_pasted(self) -> str | None:
        text = self._pasted_text
        self._pasted_text = None
        return text


class BackgroundTaskPanel(Static):
    """后台任务实时进度面板 — 仅有运行中任务时显示。"""

    DEFAULT_CSS = """
    BackgroundTaskPanel {
        dock: top;
        height: auto;
        max-height: 5;
        background: $boost;
        color: $text;
        padding: 0 1;
        border-bottom: solid $primary;
    }
    """

    def __init__(self, bg_manager, **kwargs):
        super().__init__("", **kwargs)
        self._bg_manager = bg_manager
        self.styles.display = "none"

    def on_mount(self) -> None:
        self.set_interval(1.0, self._tick)

    def _tick(self) -> None:
        tasks = self._bg_manager.active_tasks()
        if not tasks:
            if self.styles.display != "none":
                self.styles.display = "none"
            return
        if self.styles.display == "none":
            self.styles.display = "block"
        from cli.tools import TOOL_DISPLAY_NAMES

        lines = []
        for t in tasks:
            m, s = divmod(int(time.monotonic() - t.submitted_at), 60)
            stage = t.current_stage or "准备中"
            detail = f" · {t.current_detail}" if t.current_detail else ""
            name = TOOL_DISPLAY_NAMES.get(t.tool_name, t.tool_name)
            lines.append(
                f"  ⟳ {name}  {stage}{detail}    [{m}m{s:02d}s]" if m else f"  ⟳ {name}  {stage}{detail}    [{s}s]"
            )
        self.update("\n".join(lines))


class SelectorScreen(ModalScreen):
    """模态选择器 — 上下键选择，Enter 确认，Esc 取消。"""

    DEFAULT_CSS = """
    SelectorScreen {
        align: center middle;
    }
    #selector-box {
        width: 60;
        max-height: 16;
        background: $surface;
        border: thick $accent;
        padding: 1 2;
    }
    #selector-options {
        height: auto;
        max-height: 12;
    }
    """

    BINDINGS = [Binding("escape", "cancel", show=False)]

    def __init__(self, options: list[tuple[str, str]], callback_id: str):
        super().__init__()
        self._options = options
        self._values = [v for v, _ in options]
        self._callback_id = callback_id

    def compose(self) -> ComposeResult:
        with Vertical(id="selector-box"):
            yield OptionList(
                *[Option(label, id=val) for val, label in self._options],
                id="selector-options",
            )

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        value = self._values[event.option_index]
        self.dismiss(None)
        self.app._on_selector_choice(self._callback_id, value)

    def action_cancel(self) -> None:
        self.dismiss(None)
        self.app._on_selector_choice(self._callback_id, None)


_SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


# ---------------------------------------------------------------------------
# 交互式输入状态机（/login, /model）
# ---------------------------------------------------------------------------


class _InputState:
    """管理多步交互式输入流程。"""

    NONE = "none"
    LOGIN_EMAIL = "login_email"
    LOGIN_PASSWORD = "login_password"
    CONFIG_KEY = "config_key"
    MODEL_ID = "model_id"
    MODEL_PROVIDER = "model_provider"
    MODEL_KEY = "model_key"
    MODEL_NAME = "model_name"
    MODEL_URL = "model_url"
    SCHED_ID = "sched_id"
    SCHED_NAME = "sched_name"
    SCHED_CRON = "sched_cron"
    SCHED_ACTION = "sched_action"


# ---------------------------------------------------------------------------
# 工具确认弹窗
# ---------------------------------------------------------------------------


class ToolConfirmScreen(ModalScreen[dict]):
    """高风险工具执行前的确认弹窗。"""

    DEFAULT_CSS = """
    ToolConfirmScreen {
        align: center middle;
    }
    #confirm-box {
        width: 64;
        max-height: 20;
        background: $surface;
        border: thick $accent;
        padding: 1 2;
    }
    #confirm-title {
        text-style: bold;
        margin-bottom: 1;
    }
    #confirm-summary {
        color: $text-muted;
        margin-bottom: 1;
    }
    #confirm-options {
        height: auto;
        max-height: 6;
    }
    #confirm-edit {
        display: none;
        margin-top: 1;
    }
    """

    BINDINGS = [Binding("escape", "cancel", show=False)]

    def __init__(self, tool_name: str, args: dict, display_name: str):
        super().__init__()
        self.tool_name = tool_name
        self.tool_args = args
        self.display_name = display_name

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-box"):
            yield Static(
                f"⚠ [bold]{self.display_name}[/bold] 需要确认",
                id="confirm-title",
            )
            yield Static(self._format_summary(), id="confirm-summary")
            yield OptionList(
                Option("允许一次", id="once"),
                Option("本次会话总是允许", id="always"),
                Option("修改后执行", id="edit"),
                Option("不允许", id="deny"),
                id="confirm-options",
            )
            yield Input(
                value=self._editable_value(),
                placeholder="修改后按 Enter 执行",
                id="confirm-edit",
            )

    def _format_summary(self) -> str:
        if self.tool_name == "exec_command":
            return f"  命令: {self.tool_args.get('command', '')}"
        if self.tool_name == "write_file":
            path = self.tool_args.get("path", "")
            size = len(self.tool_args.get("content", ""))
            return f"  路径: {path}\n  内容: {size} 字符"
        if self.tool_name == "update_portfolio":
            action = self.tool_args.get("action", "")
            code = self.tool_args.get("code", "")
            parts = [f"操作: {action}"]
            if code:
                parts.append(f"代码: {code}")
            shares = self.tool_args.get("shares")
            if shares:
                parts.append(f"股数: {shares}")
            cost = self.tool_args.get("cost_price")
            if cost:
                parts.append(f"成本: {cost}")
            cash = self.tool_args.get("free_cash")
            if cash is not None:
                parts.append(f"现金: {cash}")
            return "  " + "  ".join(parts)
        return f"  {json.dumps(self.tool_args, ensure_ascii=False)}"

    def _editable_value(self) -> str:
        if self.tool_name == "exec_command":
            return self.tool_args.get("command", "")
        if self.tool_name == "write_file":
            return self.tool_args.get("path", "")
        return json.dumps(self.tool_args, ensure_ascii=False)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_id == "edit":
            self.query_one("#confirm-options").display = False
            edit_input = self.query_one("#confirm-edit", Input)
            edit_input.display = True
            edit_input.focus()
        else:
            self.dismiss({"action": event.option_id})

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "confirm-edit":
            return
        modified = dict(self.tool_args)
        if self.tool_name == "exec_command":
            modified["command"] = event.value
        elif self.tool_name == "write_file":
            modified["path"] = event.value
        else:
            with contextlib.suppress(json.JSONDecodeError):
                modified = json.loads(event.value)
        self.dismiss({"action": "edit", "modified_args": modified})

    def action_cancel(self) -> None:
        self.dismiss({"action": "deny"})


class AskUserScreen(ModalScreen[str]):
    """向用户提问并等待选择或输入的交互弹窗。"""

    DEFAULT_CSS = """
    AskUserScreen {
        align: center middle;
    }
    #ask-box {
        width: 64;
        max-height: 24;
        background: $surface;
        border: thick $accent;
        padding: 1 2;
    }
    #ask-title {
        text-style: bold;
        margin-bottom: 1;
    }
    #ask-question {
        height: auto;
        margin-bottom: 1;
    }
    #ask-options {
        height: auto;
        max-height: 8;
        margin-bottom: 1;
    }
    #ask-input {
        margin-top: 1;
    }
    """

    BINDINGS = [Binding("escape", "cancel", show=False)]

    def __init__(
        self,
        question: str,
        options: list[str] | None = None,
        *,
        allow_free_text: bool = True,
        default_answer: str = "",
    ):
        super().__init__()
        self.question = question
        self.options = options or []
        self.allow_free_text = allow_free_text or not self.options
        self.default_answer = default_answer

    def compose(self) -> ComposeResult:
        with Vertical(id="ask-box"):
            yield Static("需要你确认/补充", id="ask-title")
            yield Static(self.question, id="ask-question")
            if self.options:
                yield OptionList(
                    *[Option(opt, id=f"opt_{i}") for i, opt in enumerate(self.options)],
                    id="ask-options",
                )
            if self.allow_free_text:
                yield Input(value=self.default_answer, placeholder=self._input_placeholder(), id="ask-input")

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        selected_option = event.option.prompt
        self.dismiss(str(selected_option))

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value or self.default_answer)

    def action_cancel(self) -> None:
        self.dismiss("已取消回答")

    def _input_placeholder(self) -> str:
        if self.options:
            return "也可以在此输入自定义回答..."
        if self.default_answer:
            return "直接回车使用默认回答"
        return "在此输入回答并按 Enter..."


# ---------------------------------------------------------------------------
# 错误友好化
# ---------------------------------------------------------------------------


def _friendly_error(e: Exception) -> str:
    """将常见网络/超时异常转为用户可读的中文提示。"""
    import re

    cls_name = type(e).__name__
    if isinstance(e, TimeoutError):
        return "模型响应超时（60s 无数据），请检查网络"
    if "RemoteProtocolError" in cls_name or "ReadError" in cls_name:
        return "连接已断开，请检查网络后重试"
    if "APIConnectionError" in cls_name or "ConnectError" in cls_name:
        return "API 连接失败，请检查网络"
    err = str(e)
    if "<html" in err.lower():
        title = re.search(r"<title>(.*?)</title>", err, re.IGNORECASE)
        err = title.group(1) if title else "服务端返回 HTML 错误"
    if len(err) > 200:
        err = err[:200] + "..."
    return err


# ---------------------------------------------------------------------------
# 主应用
# ---------------------------------------------------------------------------


class WyckoffTUI(App):
    """威科夫终端读盘室。"""

    TITLE = "Wyckoff 读盘室"
    CSS = """
    Screen {
        layout: vertical;
    }
    #chat-log {
        height: 1fr;
        border: round $primary;
        margin: 0 1;
    }
    #chat-input {
        dock: bottom;
        margin: 0 1 0 1;
    }
    """

    ENABLE_COMMAND_PALETTE = True
    COMMAND_PALETTE_BINDING = "ctrl+p"
    COMMANDS = set()  # will be populated below after class definition

    BINDINGS = [
        Binding("ctrl+c", "smart_copy", show=False, priority=True),
        Binding("ctrl+q", "quit", "退出", show=False),
        Binding("ctrl+n", "new_chat", "新对话"),
        Binding("ctrl+l", "clear_chat", "清屏"),
    ]

    def __init__(
        self,
        provider: Any = None,
        tools: Any = None,
        state: dict | None = None,
        system_prompt: str = "",
        session_expired: bool = False,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._provider = provider
        self._tools = tools
        self._state = state or {}
        self._system_prompt = system_prompt
        self._session_expired = session_expired
        self._messages: list[dict] = []
        self._session_tokens = {"input": 0, "output": 0, "rounds": 0}
        self._busy = False
        self._cancel_event = threading.Event()
        self._last_ctrl_c: float = 0.0
        self._queue: deque[str] = deque()
        self._session_id = uuid.uuid4().hex[:12]
        self._agent_log = _get_agent_logger()
        # 后台任务管理
        from cli.background import BackgroundTaskManager

        self._bg_manager = BackgroundTaskManager()
        self._bg_manager.set_progress_callback(self._on_bg_progress)
        if self._tools:
            self._tools.set_background_manager(self._bg_manager, self._on_bg_complete)
            self._tools.set_confirm_callback(self._request_tool_confirm)
            self._tools.set_ask_user_question_callback(self._request_user_question)
        # 交互式输入状态
        self._input_mode = _InputState.NONE
        self._input_buf: dict[str, str] = {}
        # 定时调度
        from cli.scheduler import load_schedules

        self._schedules = load_schedules()

    def compose(self) -> ComposeResult:
        yield StatusBar(self._build_status_text(), id="status-bar")
        yield BackgroundTaskPanel(self._bg_manager, id="bg-panel")
        yield ChatLog(id="chat-log", highlight=True, markup=True, wrap=True)
        yield ChatInput(
            placeholder="问我关于股票的任何问题... (/help 查看命令)",
            id="chat-input",
            highlighter=_PasteHighlighter(),
        )

    def on_mount(self) -> None:
        # 加载保存的主题
        try:
            from cli.auth import load_config

            saved_theme = load_config().get("theme", "")
            if saved_theme and saved_theme in self.available_themes:
                self.theme = saved_theme
        except Exception:
            logger.debug("load saved theme failed", exc_info=True)

        log = self.query_one("#chat-log", ChatLog)
        log.write(
            Text.from_markup(
                "[bold]Wyckoff 读盘室[/bold]\n"
                "[dim]直接输入问题开始对话  ·  /help 查看命令  ·  Ctrl+P 命令面板  ·  Ctrl+C 复制/退出[/dim]\n"
            )
        )
        if not self._provider:
            log.write(Text.from_markup("[yellow]⚠ 未配置模型，请输入 /model add 添加[/yellow]\n"))
        if self._session_expired:
            log.write(Text.from_markup("[yellow]⚠ 登录已过期，请输入 /login 重新登录[/yellow]\n"))
        self.query_one("#chat-input", Input).focus()
        if self._schedules:
            self.set_interval(60.0, self._check_schedules)

    def _build_status_text(self) -> str:
        from importlib.metadata import version as _ver

        try:
            ver = _ver("youngcan-wyckoff-analysis")
        except Exception:
            ver = "?"
        parts = [f"Wyckoff CLI v{ver}"]
        prov = self._state.get("provider_name", "")
        model = self._state.get("model", "")
        if prov and model:
            parts.append(f"{prov}:{model}")
        email = self._tools.state.get("email", "") if self._tools else ""
        parts.append(email or "未登录")
        parts.append(f"#{self._session_id}")
        t = self._session_tokens
        if t["rounds"] > 0:
            parts.append(f"Token: {t['input'] + t['output']:,}")
        return " · ".join(parts)

    def _update_status(self) -> None:
        self.query_one("#status-bar", StatusBar).update(self._build_status_text())

    # ----- 工具确认 -----

    def _request_tool_confirm(self, name: str, args: dict) -> dict:
        """从 worker 线程调用，阻塞直到用户在弹窗中做出选择。"""
        event = threading.Event()
        result: list[dict | None] = [None]
        display = self._tools.display_name(name) if self._tools else name

        def _on_dismiss(choice: dict) -> None:
            result[0] = choice
            event.set()

        def _show() -> None:
            self.push_screen(ToolConfirmScreen(name, args, display), _on_dismiss)

        self.call_from_thread(_show)
        event.wait(timeout=120)
        return result[0] or {"action": "deny"}

    def _request_user_question(
        self,
        question: str,
        options: list[str] | None = None,
        allow_free_text: bool = True,
        default_answer: str = "",
    ) -> str:
        """从 worker 线程调用，阻塞并向用户提问，返回用户的回答。"""
        event = threading.Event()
        result: list[str] = [""]

        def _on_dismiss(answer: str) -> None:
            result[0] = answer
            event.set()

        def _show() -> None:
            screen = AskUserScreen(
                question,
                options,
                allow_free_text=allow_free_text,
                default_answer=default_answer,
            )
            self.push_screen(screen, _on_dismiss)

        self.call_from_thread(_show)
        event.wait(timeout=300)  # 等待最长 5 分钟
        return result[0] or default_answer or "已超时未作答"

    # ----- 快捷键动作 -----

    def _save_memory_async(
        self, messages: list[dict] | None = None, *, wait_timeout: float | None = None, skip_layers: bool = False
    ) -> None:
        if not self._provider:
            return
        msgs = list(messages if messages is not None else self._messages)
        if not msgs:
            return
        try:
            from cli.memory import save_session_summary

            t = threading.Thread(
                target=save_session_summary,
                args=(msgs, self._provider),
                kwargs={"session_id": self._session_id, "skip_layers": skip_layers},
                daemon=True,
            )
            t.start()
            if wait_timeout is not None:
                t.join(timeout=wait_timeout)
        except Exception:
            logger.debug("save session summary failed", exc_info=True)

    def _save_and_exit(self) -> None:
        self._save_memory_async(wait_timeout=5, skip_layers=True)
        self.exit()

    def action_quit(self) -> None:
        self._save_and_exit()

    def action_smart_copy(self) -> None:
        """Ctrl+C: 选中文本→复制；执行中→中断；空闲双击1s内→退出。"""
        text = self.screen.get_selected_text()
        if text:
            self.copy_to_clipboard(text)
            self.screen.clear_selection()
            self.notify("已复制", timeout=1)
            return
        if self._busy:
            self._cancel_event.set()
            self.notify("已中断", timeout=1)
            return
        now = time.monotonic()
        if now - self._last_ctrl_c < 1.0:
            self._save_and_exit()
        else:
            self._last_ctrl_c = now
            self.notify("再按一次 Ctrl+C 退出", timeout=1)

    def action_switch_model(self) -> None:
        self._switch_model_selector()

    def action_list_models(self) -> None:
        self._list_models()

    def action_add_model(self) -> None:
        self._start_model_add()

    def action_start_login(self) -> None:
        self._start_login()

    def action_do_logout(self) -> None:
        self._do_logout()

    def action_show_token(self) -> None:
        log = self.query_one("#chat-log", ChatLog)
        t = self._session_tokens
        if t["rounds"] == 0:
            log.write(Text.from_markup("[dim]本次会话尚无 Token 记录[/dim]"))
        else:
            log.write(
                Text.from_markup(
                    f"\n[bold]Token 用量[/bold]  "
                    f"输入: {t['input']:,}  输出: {t['output']:,}  "
                    f"合计: {t['input'] + t['output']:,}  轮次: {t['rounds']}"
                )
            )

    def action_show_prompt_templates(self) -> None:
        self._show_prompt_templates()

    def action_show_workflows(self) -> None:
        self._show_workflows()

    def action_switch_theme(self) -> None:
        """打开主题切换器并保存选择。"""
        self.action_change_theme()

    def watch_theme(self, new_theme: str) -> None:
        """主题变化时自动保存。"""
        try:
            from cli.auth import save_config_key

            save_config_key("theme", new_theme)
        except Exception:
            logger.debug("save theme preference failed", exc_info=True)

    # ----- Spinner（ChatLog 底部边框） -----

    def _start_spinner(self, label: str = "thinking") -> None:
        self._spinner_label = label
        self._spinner_idx = 0
        log = self.query_one("#chat-log", ChatLog)
        log.border_subtitle = f"{_SPINNER[0]} {label}"
        if not hasattr(self, "_spinner_timer") or self._spinner_timer is None:
            self._spinner_timer = self.set_interval(0.08, self._tick_spinner)

    def _stop_spinner(self) -> None:
        if hasattr(self, "_spinner_timer") and self._spinner_timer is not None:
            self._spinner_timer.stop()
            self._spinner_timer = None
        self.query_one("#chat-log", ChatLog).border_subtitle = ""

    def _tick_spinner(self) -> None:
        self._spinner_idx = (self._spinner_idx + 1) % len(_SPINNER)
        self.query_one("#chat-log", ChatLog).border_subtitle = f"{_SPINNER[self._spinner_idx]} {self._spinner_label}"

    # ----- 输入处理 -----

    def on_input_submitted(self, event: Input.Submitted) -> None:
        inp = self.query_one("#chat-input", ChatInput)
        text = (inp.consume_pasted() or event.value).strip()
        inp.clear()
        inp._pasted_text = None

        # 交互式多步输入
        if self._input_mode != _InputState.NONE:
            self._handle_interactive_input(text)
            return

        if not text:
            return

        log = self.query_one("#chat-log", ChatLog)

        # 斜杠命令
        if text.startswith("/"):
            self._handle_command(text)
            return

        if not self._provider:
            log.write(Text.from_markup("[yellow]⚠ 未配置模型，请先输入 /model add[/yellow]"))
            return

        if self._busy:
            self._queue.append(text)
            log.write(Text.from_markup("  [dim]📋 已排队（等待当前回复完成后自动发送）[/dim]"))
            return

        # 用户消息
        self._send_message(text)

    def _send_message(self, text: str) -> None:
        log = self.query_one("#chat-log", ChatLog)
        log.write(Text(""))
        lines = text.splitlines()
        if len(lines) > 3:
            preview = "\n".join(lines[:3]) + f"\n... ({len(lines)} lines total)"
            log.write(Text.from_markup(f"[bold cyan]❯[/bold cyan] {preview}"))
        else:
            log.write(Text.from_markup(f"[bold cyan]❯[/bold cyan] {text}"))
        # 注入记忆上下文
        mem_ctx = ""
        try:
            from cli.memory import build_memory_context

            mem_ctx = build_memory_context(text)
        except Exception:
            logger.debug("memory context injection failed", exc_info=True)
        user_message = {"role": "user", "content": text}
        if mem_ctx:
            user_message["_memory_context"] = mem_ctx
        self._messages.append(user_message)
        self._start_spinner("thinking")
        self._run_agent()

    # ----- 斜杠命令 -----

    def _handle_command(self, raw: str) -> None:
        cmd = raw.lower().split()[0]
        log = self.query_one("#chat-log", ChatLog)

        if cmd in ("/quit", "/exit", "/q"):
            self._save_and_exit()
        elif cmd == "/clear":
            self.action_clear_chat()
        elif cmd == "/new":
            self.action_new_chat()
        elif cmd == "/help":
            from cli.prompt_templates import load_prompt_templates
            from cli.skills import load_skills

            templates = load_prompt_templates()
            skills = load_skills()
            template_lines = "".join(f"  /{t.name:<11s}— {t.description}\n" for t in templates.values())
            skill_lines = "".join(f"  /{s.name:<11s}— {s.description}\n" for s in skills.values())
            log.write(
                Text.from_markup(
                    "\n[bold]可用命令[/bold]\n"
                    "  /model   — 切换模型（list/add/rm/default）\n"
                    "  /config  — 数据源配置（tushare_token, tickflow_api_key）\n"
                    "  /login   — 登录\n"
                    "  /logout  — 退出登录\n"
                    "  /token   — Token 用量\n"
                    "  /changelog— 版本更新日志\n"
                    "  /prompt  — Prompt 模板（list/show/<name>）\n"
                    "  /workflow— 最近动态 workflow\n"
                    "  /schedule— 定时任务（list/add/rm/on/off）\n"
                    "  /resume  — 恢复历史对话\n"
                    "  /fork    — 分叉当前会话\n"
                    "  /new     — 新对话 (Ctrl+N)\n"
                    "  /clear   — 清屏 (Ctrl+L)\n"
                    "  /quit    — 退出 (Ctrl+Q)\n"
                    f"\n[bold]Skills[/bold]\n{skill_lines}"
                    f"\n[bold]Prompt Templates[/bold]\n{template_lines}"
                    "\n[bold]快捷键[/bold]\n"
                    "  Ctrl+P   — 命令面板\n"
                    "  Ctrl+C   — 复制选中文本 / 退出\n"
                    "  Ctrl+N   — 新对话\n"
                    "  Ctrl+L   — 清屏\n"
                    "  鼠标拖选  — 选择文本\n"
                )
            )
        elif cmd == "/token":
            t = self._session_tokens
            if t["rounds"] == 0:
                log.write(Text.from_markup("[dim]本次会话尚无 Token 记录[/dim]"))
            else:
                log.write(
                    Text.from_markup(
                        f"\n[bold]Token 用量[/bold]  "
                        f"输入: {t['input']:,}  输出: {t['output']:,}  "
                        f"合计: {t['input'] + t['output']:,}  轮次: {t['rounds']}"
                    )
                )
        elif cmd == "/login":
            self._start_login()
        elif cmd == "/logout":
            self._do_logout()
        elif cmd == "/config":
            parts = raw.strip().split(maxsplit=2)
            if len(parts) == 1:
                self._show_config()
            elif parts[1] == "set" and len(parts) >= 3:
                self._start_config_set(parts[2])
            else:
                log.write(
                    Text.from_markup(
                        "[dim]/config 用法: /config (查看) | /config set tushare_token | /config set tickflow_api_key[/dim]"
                    )
                )
        elif cmd == "/model":
            parts = raw.strip().split()
            if len(parts) == 1:
                self._switch_model_selector()
            elif parts[1] == "list":
                self._list_models()
            elif parts[1] == "add":
                self._start_model_add()
            elif parts[1] == "rm" and len(parts) >= 3:
                self._remove_model(parts[2])
            elif parts[1] == "default" and len(parts) >= 3:
                self._set_default_model(parts[2])
            else:
                log.write(
                    Text.from_markup(
                        "[dim]/model 用法: /model (切换) | /model list | /model add | /model rm <id> | /model default <id>[/dim]"
                    )
                )
        elif cmd == "/changelog":
            self._show_changelog(log)
        elif cmd == "/prompt":
            self._handle_prompt_cmd(raw, log)
        elif cmd in ("/workflow", "/wf"):
            self._handle_workflow_cmd(raw, log)
        elif cmd == "/resume":
            parts = raw.strip().split(maxsplit=1)
            if len(parts) > 1:
                self._resume_session(parts[1].strip())
            else:
                self._resume_session_selector()
        elif cmd == "/fork":
            self.action_fork_session()
        elif cmd == "/schedule":
            self._handle_schedule_cmd(raw, log)
        else:
            self._try_skill(raw, log)

    def _show_changelog(self, log) -> None:
        from pathlib import Path

        path = Path(__file__).resolve().parent.parent / "CHANGELOG.md"
        if not path.exists():
            log.write(Text.from_markup("[dim]CHANGELOG.md 不存在[/dim]"))
            return
        text = path.read_text(encoding="utf-8").strip()
        lines = text.splitlines()
        # 只显示最近一个版本段落（到下一个 ## 或结尾）
        start = next((i for i, l in enumerate(lines) if l.startswith("## ")), 0)
        end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
        section = "\n".join(lines[start:end]).strip()
        log.write(Text.from_markup(f"\n[bold]{section}[/bold]\n"))

    # ----- Skills -----

    def _try_skill(self, raw: str, log) -> None:
        from cli.prompt_templates import load_prompt_templates
        from cli.skills import load_skills

        templates = load_prompt_templates()
        skills = load_skills()
        parts = raw.strip().split(maxsplit=1)
        cmd_name = parts[0].lstrip("/").lower()
        user_input = parts[1] if len(parts) > 1 else ""
        if cmd_name in skills:
            self._execute_skill(cmd_name, user_input)
        elif cmd_name in templates:
            self._execute_prompt_template(cmd_name, user_input)
        else:
            log.write(Text.from_markup(f"[red]未知命令: {raw}[/red]，/help 查看"))

    def _execute_skill(self, name: str, user_input: str = "") -> None:
        from cli.skills import load_skills

        log = self.query_one("#chat-log", ChatLog)
        skills = load_skills()
        skill = skills.get(name)
        if not skill:
            log.write(Text.from_markup(f"[red]未知 skill: {name}[/red]"))
            return
        if not self._provider:
            log.write(Text.from_markup("[yellow]⚠ 未配置模型，请先输入 /model add[/yellow]"))
            return
        prompt = skill.prompt.replace("{user_input}", user_input).strip()
        self._send_message(prompt)

    def action_run_skill(self, name: str) -> None:
        """命令面板调用 skill 入口。"""
        self._execute_skill(name)

    # ----- Prompt Templates -----

    def _handle_workflow_cmd(self, raw: str, log) -> None:
        parts = raw.strip().split(maxsplit=2)
        if len(parts) >= 3 and parts[1] == "resume":
            self._resume_workflow(parts[2].strip(), log)
            return
        self._show_workflows()

    def _resume_workflow(self, run_id: str, log) -> None:
        from cli.workflows.resume import build_resume_prompt
        from cli.workflows.store import get_workflow_run

        run = get_workflow_run(run_id)
        if not run:
            log.write(Text.from_markup(f"[red]未找到 workflow: {escape(run_id)}[/red]"))
            return
        self._send_message(build_resume_prompt(run))

    def _show_workflows(self) -> None:
        from cli.workflows.store import list_workflow_runs

        log = self.query_one("#chat-log", ChatLog)
        rows = list_workflow_runs(limit=8)
        if not rows:
            log.write(Text.from_markup("[dim]暂无 workflow 记录[/dim]"))
            return
        lines = ["\n[bold]最近 workflow[/bold]"]
        for row in rows:
            lines.append(
                f"  [cyan]{row['run_id']}[/cyan] {row['status']} {row['label']} "
                f"[dim]{str(row.get('user_text', ''))[:48]}[/dim]"
            )
        log.write(Text.from_markup("\n".join(lines)))

    def _show_prompt_templates(self) -> None:
        from cli.prompt_templates import load_prompt_templates

        log = self.query_one("#chat-log", ChatLog)
        templates = load_prompt_templates()
        if not templates:
            log.write(Text.from_markup("[dim]暂无 Prompt 模板[/dim]"))
            return
        lines = ["\n[bold]Prompt 模板[/bold]"]
        for tpl in templates.values():
            hint = f" [dim]{tpl.argument_hint}[/dim]" if tpl.argument_hint else ""
            lines.append(f"  [cyan]/{tpl.name:<13}[/cyan] {tpl.description}{hint}")
        lines.append("\n[dim]用法: /prompt <name> [补充说明]，也可以直接输入 /daily 这类模板名[/dim]")
        log.write(Text.from_markup("\n".join(lines)))

    def _handle_prompt_cmd(self, raw: str, log) -> None:
        from cli.prompt_templates import load_prompt_templates

        templates = load_prompt_templates()
        parts = raw.strip().split(maxsplit=2)
        if len(parts) == 1 or parts[1] == "list":
            self._show_prompt_templates()
            return
        if parts[1] == "show":
            if len(parts) < 3:
                log.write(Text.from_markup("[dim]用法: /prompt show <name>[/dim]"))
                return
            tpl = templates.get(parts[2].strip().lower())
            if not tpl:
                log.write(Text.from_markup(f"[red]未知 Prompt 模板: {parts[2]}[/red]"))
                return
            body = tpl.prompt.replace("[", "\\[").replace("]", "\\]")
            log.write(Text.from_markup(f"\n[bold]{tpl.name}[/bold] — {tpl.description}\n\n[dim]{body}[/dim]"))
            return
        name = parts[1].strip().lower()
        user_input = parts[2] if len(parts) > 2 else ""
        self._execute_prompt_template(name, user_input)

    def _execute_prompt_template(self, name: str, user_input: str = "") -> None:
        from cli.prompt_templates import load_prompt_templates, render_prompt_template

        log = self.query_one("#chat-log", ChatLog)
        templates = load_prompt_templates()
        template = templates.get(name)
        if not template:
            log.write(Text.from_markup(f"[red]未知 Prompt 模板: {name}[/red]"))
            return
        if not self._provider:
            log.write(Text.from_markup("[yellow]⚠ 未配置模型，请先输入 /model add[/yellow]"))
            return
        prompt = render_prompt_template(template, user_input)
        self._send_message(prompt)

    def action_run_template(self, name: str) -> None:
        """命令面板调用 Prompt 模板入口。"""
        self._execute_prompt_template(name)

    # ----- /config 交互 -----

    _CONFIG_KEYS = {
        "tushare_token": ("Tushare Token", "TUSHARE_TOKEN", ""),
        "tickflow_api_key": (
            "TickFlow API Key",
            "TICKFLOW_API_KEY",
            "购买: https://tickflow.org/auth/register?ref=5N4NKTCPL4",
        ),
    }

    def _show_config(self) -> None:
        log = self.query_one("#chat-log", ChatLog)
        from cli.auth import load_config

        cfg = load_config()
        log.write(Text.from_markup("\n[bold]数据源配置[/bold]"))
        for key, (label, _, hint) in self._CONFIG_KEYS.items():
            val = str(cfg.get(key, "") or "").strip()
            if val:
                masked = val[:4] + "****" + val[-4:] if len(val) > 8 else "****"
                log.write(Text.from_markup(f"  {label}: [green]{masked}[/green]"))
            else:
                log.write(Text.from_markup(f"  {label}: [dim]未配置[/dim] — {hint}"))
        log.write(Text.from_markup("\n[dim]使用 /config set tushare_token 或 /config set tickflow_api_key 配置[/dim]"))

    def _start_config_set(self, key: str) -> None:
        log = self.query_one("#chat-log", ChatLog)
        inp = self.query_one("#chat-input", Input)
        key = key.strip().lower()
        if key not in self._CONFIG_KEYS:
            log.write(Text.from_markup(f"[red]不支持的配置项: {key}[/red]，可选: {', '.join(self._CONFIG_KEYS)}"))
            return
        label, _, hint = self._CONFIG_KEYS[key]
        log.write(Text.from_markup(f"\n[bold]配置 {label}[/bold]"))
        log.write(Text.from_markup(f"  {hint}"))
        log.write(Text.from_markup("  输入值（留空取消）："))
        inp.placeholder = f"{label}..."
        inp.password = True
        self._input_mode = _InputState.CONFIG_KEY
        self._input_buf = {"config_key": key}

    # ----- /login 交互 -----

    def _start_login(self) -> None:
        log = self.query_one("#chat-log", ChatLog)
        inp = self.query_one("#chat-input", Input)
        log.write(Text.from_markup("\n[bold]登录[/bold]"))
        log.write(Text.from_markup("  输入邮箱（留空取消）："))
        inp.placeholder = "邮箱..."
        self._input_mode = _InputState.LOGIN_EMAIL
        self._input_buf = {}

    def _do_logout(self) -> None:
        log = self.query_one("#chat-log", ChatLog)
        if self._tools:
            try:
                from cli.auth import logout

                logout()
            except Exception:
                logger.warning("logout failed", exc_info=True)
            self._tools.state.update({"user_id": "", "email": "", "access_token": "", "refresh_token": ""})
        log.write(Text.from_markup("[green]已退出登录[/green]"))
        self._update_status()

    # ----- /model 交互 -----

    def _list_models(self) -> None:
        log = self.query_one("#chat-log", ChatLog)
        from cli.auth import load_default_model_id, load_model_configs
        from cli.model_registry import format_model_metadata, infer_model_info

        configs = load_model_configs()
        default_id = load_default_model_id()
        if not configs:
            log.write(Text.from_markup("[dim]尚无模型配置，使用 /model add 添加[/dim]"))
            return
        log.write(Text.from_markup("\n[bold]已配置模型[/bold] [dim](↑↓选择 Enter确认 Esc取消)[/dim]"))
        for c in configs:
            mark = " [green]⭐ 默认[/green]" if c["id"] == default_id else ""
            metadata = format_model_metadata(infer_model_info(c))
            log.write(
                Text.from_markup(
                    f"  [bold]{c['id']}[/bold] — {c['provider_name']}/{c.get('model', '?')} [dim]{metadata}[/dim]{mark}"
                )
            )
        self._switch_model_selector()

    def _remove_model(self, model_id: str) -> None:
        log = self.query_one("#chat-log", ChatLog)
        from cli.auth import remove_model_entry

        if remove_model_entry(model_id):
            log.write(Text.from_markup(f"  [green]✓ 已删除 {model_id}[/green]"))
            self._rebuild_provider()
        else:
            log.write(Text.from_markup("  [red]无法删除（至少保留一个模型）[/red]"))

    def _set_default_model(self, model_id: str) -> None:
        log = self.query_one("#chat-log", ChatLog)
        from cli.auth import load_model_configs, set_default_model

        configs = load_model_configs()
        if not any(c["id"] == model_id for c in configs):
            log.write(Text.from_markup(f"  [red]未找到: {model_id}[/red]"))
            return
        set_default_model(model_id)
        log.write(Text.from_markup(f"  [green]✓ 默认模型已设为 {model_id}[/green]"))
        self._rebuild_provider()

    def _rebuild_provider(self) -> None:
        from cli.auth import load_default_model_id, load_fallback_model_id, load_model_configs

        configs = load_model_configs()
        default_id = load_default_model_id()
        if not configs:
            self._provider = None
            return
        default_cfg = next((c for c in configs if c["id"] == default_id), configs[0])
        if len(configs) == 1:
            from cli._provider_factory import _create_provider, provider_config_kwargs

            provider, err = _create_provider(**provider_config_kwargs(default_cfg))
            if not err:
                self._provider = provider
        else:
            from cli.providers.fallback import FallbackProvider

            self._provider = FallbackProvider(configs, default_id, fallback_id=load_fallback_model_id())
        self._state.update(default_cfg)
        if self._tools and self._provider:
            self._tools.set_provider(self._provider)
        self._update_status()

    def _show_selector(self, options: list[tuple[str, str]], callback_id: str) -> None:
        """显示模态选择器。options: [(value, label), ...]"""
        self.push_screen(SelectorScreen(options, callback_id))

    def _dismiss_selector(self) -> None:
        self.query_one("#chat-input", Input).focus()

    def _on_selector_choice(self, callback_id: str, value: str | None) -> None:
        """选择器回调。"""
        self._dismiss_selector()
        log = self.query_one("#chat-log", ChatLog)
        inp = self.query_one("#chat-input", Input)

        if value is None:
            log.write(Text.from_markup("[dim]已取消[/dim]"))
            self._input_mode = _InputState.NONE
            inp.placeholder = "问我关于股票的任何问题... (/help 查看命令)"
            return

        if callback_id == "model_switch":
            self._set_default_model(value)

        elif callback_id == "session_resume":
            self._resume_session(value)

        elif callback_id == "model_provider":
            self._input_buf["provider"] = value
            log.write(Text.from_markup(f"  供应商: {value}"))
            log.write(
                Text.from_markup(
                    "  输入 API Key（购买: [link=https://www.1route.dev/register?aff=359904261]1route.dev[/link]）："
                )
            )
            inp.placeholder = "API Key..."
            inp.password = True
            self._input_mode = _InputState.MODEL_KEY

    def _switch_model_selector(self) -> None:
        """弹出浮层选择器切换当前模型。"""
        from cli.auth import load_default_model_id, load_model_configs
        from cli.model_registry import format_token_window, infer_model_info

        configs = load_model_configs()
        if not configs:
            log = self.query_one("#chat-log", ChatLog)
            log.write(Text.from_markup("[dim]尚无模型配置，使用 /model add 添加[/dim]"))
            return
        default_id = load_default_model_id()
        options = []
        for c in configs:
            mark = " ⭐" if c["id"] == default_id else ""
            info = infer_model_info(c)
            label = f"{c['id']} ({c.get('model', '?')} · ctx {format_token_window(info.context_window)}){mark}"
            options.append((c["id"], label))
        self._show_selector(options, "model_switch")

    def _start_model_add(self) -> None:
        log = self.query_one("#chat-log", ChatLog)
        inp = self.query_one("#chat-input", Input)
        log.write(Text.from_markup("\n[bold]添加模型[/bold]\n  输入别名（如 gemini, longcat, deepseek）："))
        inp.placeholder = "模型别名..."
        self._input_mode = _InputState.MODEL_ID
        self._input_buf = {}

    # ----- 交互式输入状态机 -----

    def _handle_interactive_input(self, text: str) -> None:
        log = self.query_one("#chat-log", ChatLog)
        inp = self.query_one("#chat-input", Input)
        mode = self._input_mode

        # MODEL_NAME 和 MODEL_URL 留空表示用默认值，不取消
        if not text and mode not in (_InputState.MODEL_NAME, _InputState.MODEL_URL, _InputState.MODEL_ID):
            log.write(Text.from_markup("[dim]已取消[/dim]"))
            self._input_mode = _InputState.NONE
            inp.placeholder = "问我关于股票的任何问题... (/help 查看命令)"
            return

        if mode == _InputState.CONFIG_KEY:
            inp.password = False
            key = self._input_buf["config_key"]
            label, env_key, _ = self._CONFIG_KEYS[key]
            from cli.auth import save_config_key

            save_config_key(key, text)
            import os

            os.environ[env_key] = text
            log.write(Text.from_markup(f"  [green]✓ {label} 已保存[/green]"))
            self._input_mode = _InputState.NONE
            inp.placeholder = "问我关于股票的任何问题... (/help 查看命令)"
            return

        elif mode == _InputState.LOGIN_EMAIL:
            self._input_buf["email"] = text
            log.write(Text.from_markup(f"  邮箱: {text}"))
            log.write(Text.from_markup("  输入密码："))
            inp.placeholder = "密码..."
            inp.password = True
            self._input_mode = _InputState.LOGIN_PASSWORD

        elif mode == _InputState.LOGIN_PASSWORD:
            inp.password = False
            log.write(Text.from_markup("  密码: ****"))
            self._input_mode = _InputState.NONE
            inp.placeholder = "问我关于股票的任何问题... (/help 查看命令)"
            # 执行登录
            try:
                from cli.auth import login

                session = login(self._input_buf["email"], text)
                self._tools.state.update(
                    {
                        "user_id": session["user_id"],
                        "email": session["email"],
                        "access_token": session.get("access_token", ""),
                        "refresh_token": session.get("refresh_token", ""),
                    }
                )
                log.write(Text.from_markup(f"  [green]✓ 登录成功 ({session['email']})[/green]"))
                self._update_status()
            except Exception as e:
                err = str(e)
                if "Invalid login" in err or "invalid" in err.lower():
                    log.write(Text.from_markup("  [red]邮箱或密码错误，请重新输入[/red]"))
                else:
                    log.write(Text.from_markup(f"  [red]登录失败: {err}，请重新输入[/red]"))
                self._start_login()

        elif mode == _InputState.MODEL_ID:
            model_id = text.strip().lower() if text.strip() else ""
            if not model_id:
                log.write(Text.from_markup("[dim]已取消[/dim]"))
                self._input_mode = _InputState.NONE
                inp.placeholder = "问我关于股票的任何问题... (/help 查看命令)"
                return
            self._input_buf["id"] = model_id
            log.write(Text.from_markup(f"  别名: {model_id}"))
            log.write(Text.from_markup("  选择供应商（↑↓ 选择，Enter 确认，Esc 取消）："))
            self._input_mode = _InputState.MODEL_PROVIDER
            self._show_selector(
                [
                    ("gemini", "Gemini (Google)"),
                    ("openai", "OpenAI / 兼容接口 (LongCat, DeepSeek, Qwen...)"),
                    ("claude", "Claude (Anthropic)"),
                ],
                "model_provider",
            )
            return  # 等 selector 回调

        elif mode == _InputState.MODEL_PROVIDER:
            # 文本输入兜底（selector 取消后手动输入）
            prov = text.strip().lower()
            if prov not in ("gemini", "openai", "claude"):
                log.write(Text.from_markup(f"  [red]不支持: {prov}[/red]"))
                self._input_mode = _InputState.NONE
                inp.placeholder = "问我关于股票的任何问题... (/help 查看命令)"
                return
            self._input_buf["provider"] = prov
            log.write(Text.from_markup(f"  供应商: {prov}"))
            log.write(
                Text.from_markup(
                    "  输入 API Key（购买: [link=https://www.1route.dev/register?aff=359904261]1route.dev[/link]）："
                )
            )
            inp.placeholder = "API Key..."
            inp.password = True
            self._input_mode = _InputState.MODEL_KEY

        elif mode == _InputState.MODEL_KEY:
            inp.password = False
            self._input_buf["api_key"] = text
            log.write(Text.from_markup("  API Key: ****"))
            default_models = {"gemini": "gemini-2.0-flash", "openai": "gpt-4o", "claude": "claude-sonnet-4-20250514"}
            default = default_models.get(self._input_buf["provider"], "")
            log.write(Text.from_markup(f"  输入模型名（留空使用 {default}）："))
            inp.placeholder = f"模型名，默认 {default}"
            self._input_mode = _InputState.MODEL_NAME

        elif mode == _InputState.MODEL_NAME:
            default_models = {"gemini": "gemini-2.0-flash", "openai": "gpt-4o", "claude": "claude-sonnet-4-20250514"}
            model = text or default_models.get(self._input_buf["provider"], "")
            self._input_buf["model"] = model
            log.write(Text.from_markup(f"  模型: {model}"))
            log.write(Text.from_markup("  输入 Base URL（留空使用默认）："))
            inp.placeholder = "Base URL（可选）"
            self._input_mode = _InputState.MODEL_URL

        elif mode == _InputState.MODEL_URL:
            self._input_buf["base_url"] = text
            self._input_mode = _InputState.NONE
            inp.placeholder = "问我关于股票的任何问题... (/help 查看命令)"
            self._apply_model_config()

        elif mode in (_InputState.SCHED_ID, _InputState.SCHED_NAME, _InputState.SCHED_CRON, _InputState.SCHED_ACTION):
            self._handle_sched_input(mode, text, log, inp)

    def _apply_model_config(self) -> None:
        log = self.query_one("#chat-log", ChatLog)
        buf = self._input_buf
        try:
            entry = {
                "id": buf.get("id", buf["provider"]),
                "provider_name": buf["provider"],
                "api_key": buf["api_key"],
                "model": buf.get("model", ""),
                "base_url": buf.get("base_url", ""),
            }
            from cli.auth import load_model_configs, save_model_entry, set_default_model

            save_model_entry(entry)
            # 首条模型或新添加的设为默认
            if len(load_model_configs()) == 1:
                set_default_model(entry["id"])
            import os

            env_key = {"gemini": "GEMINI_API_KEY", "claude": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}.get(
                buf["provider"]
            )
            if env_key:
                os.environ[env_key] = buf["api_key"]
            self._rebuild_provider()
            log.write(
                Text.from_markup(
                    f"  [green]✓ 已添加 {entry['id']} ({self._provider.name if self._provider else '?'})[/green]"
                )
            )
        except Exception as e:
            log.write(Text.from_markup(f"  [red]配置失败: {e}[/red]"))

    # ----- 定时调度 -----

    def _handle_schedule_cmd(self, raw: str, log) -> None:
        parts = raw.strip().split()
        sub = parts[1] if len(parts) > 1 else "list"
        if sub == "list":
            self._schedule_list(log)
        elif sub == "add":
            self._schedule_add_start(log)
        elif sub == "rm" and len(parts) > 2:
            self._schedule_remove(parts[2], log)
        elif sub == "on" and len(parts) > 2:
            self._schedule_toggle(parts[2], True, log)
        elif sub == "off" and len(parts) > 2:
            self._schedule_toggle(parts[2], False, log)
        else:
            log.write(Text.from_markup("[dim]/schedule 用法: list | add | rm <id> | on <id> | off <id>[/dim]"))

    def _schedule_list(self, log) -> None:
        if not self._schedules:
            log.write(Text.from_markup("[dim]暂无定时任务。使用 /schedule add 创建[/dim]"))
            return
        log.write(Text.from_markup("\n[bold]定时任务[/bold]"))
        for s in self._schedules:
            icon = "[green]●[/green]" if s.enabled else "[dim]○[/dim]"
            log.write(Text.from_markup(f"  {icon} [bold]{s.id}[/bold] — {s.name}  [dim]{s.cron}[/dim]  → {s.action}"))

    def _handle_sched_input(self, mode: str, text: str, log, inp) -> None:
        if mode == _InputState.SCHED_ID:
            self._input_buf["id"] = text
            log.write(Text.from_markup("  输入任务名称（如：盘前风控）："))
            inp.placeholder = "任务名称"
            self._input_mode = _InputState.SCHED_NAME
        elif mode == _InputState.SCHED_NAME:
            self._input_buf["name"] = text
            log.write(Text.from_markup("  输入 cron 表达式（如：25 9 * * 1-5）："))
            inp.placeholder = "分 时 日 月 周"
            self._input_mode = _InputState.SCHED_CRON
        elif mode == _InputState.SCHED_CRON:
            self._input_buf["cron"] = text
            log.write(Text.from_markup("  输入触发动作（/skill 或自由文本）："))
            inp.placeholder = "如 /checkup 或 帮我看看大盘"
            self._input_mode = _InputState.SCHED_ACTION
        elif mode == _InputState.SCHED_ACTION:
            self._input_mode = _InputState.NONE
            inp.placeholder = "问我关于股票的任何问题... (/help 查看命令)"
            self._finish_schedule_add(text, log)

    def _schedule_add_start(self, log) -> None:
        log.write(Text.from_markup("\n[bold]添加定时任务[/bold]"))
        log.write(Text.from_markup("  输入任务 ID（如：mkt-open）："))
        inp = self.query_one("#chat-input", Input)
        inp.placeholder = "任务 ID"
        self._input_mode = _InputState.SCHED_ID
        self._input_buf = {}

    def _finish_schedule_add(self, action: str, log) -> None:
        from cli.scheduler import Schedule, save_schedules

        s = Schedule(
            id=self._input_buf["id"],
            name=self._input_buf["name"],
            cron=self._input_buf["cron"],
            action=action,
        )
        self._schedules.append(s)
        save_schedules(self._schedules)
        log.write(Text.from_markup(f"  [green]✓ 已添加 {s.id} ({s.cron} → {s.action})[/green]"))

    def _schedule_remove(self, sched_id: str, log) -> None:
        from cli.scheduler import save_schedules

        before = len(self._schedules)
        self._schedules = [s for s in self._schedules if s.id != sched_id]
        if len(self._schedules) < before:
            save_schedules(self._schedules)
            log.write(Text.from_markup(f"  [green]✓ 已删除 {sched_id}[/green]"))
        else:
            log.write(Text.from_markup(f"  [red]未找到: {sched_id}[/red]"))

    def _schedule_toggle(self, sched_id: str, enable: bool, log) -> None:
        from cli.scheduler import save_schedules

        for s in self._schedules:
            if s.id == sched_id:
                s.enabled = enable
                save_schedules(self._schedules)
                log.write(Text.from_markup(f"  [green]✓ {sched_id} 已{'启用' if enable else '禁用'}[/green]"))
                return
        log.write(Text.from_markup(f"  [red]未找到: {sched_id}[/red]"))

    def _check_schedules(self) -> None:
        from datetime import datetime

        from cli.scheduler import cron_matches_now, save_schedules

        now_min = datetime.now().strftime("%Y-%m-%dT%H:%M")
        fired = False
        for s in self._schedules:
            if not s.enabled or s.last_fired.startswith(now_min):
                continue
            if cron_matches_now(s.cron):
                s.last_fired = now_min
                fired = True
                self._fire_schedule(s)
        if fired:
            save_schedules(self._schedules)

    def _fire_schedule(self, sched) -> None:
        log = self.query_one("#chat-log", ChatLog)
        log.write(Text.from_markup(f"\n[bold yellow]⏰ 定时触发：{sched.name}[/bold yellow]"))
        if sched.notify:
            self._desktop_notify(f"Wyckoff: {sched.name}")
        action = sched.action.strip()
        if action.startswith("/"):
            self._handle_command(action)
        elif self._busy:
            self._queue.append(action)
            log.write(Text.from_markup("  [dim]📋 Agent 忙碌中，已排队[/dim]"))
        else:
            self._send_message(action)

    def _desktop_notify(self, message: str) -> None:
        import subprocess
        import sys

        try:
            if sys.platform == "darwin":
                subprocess.Popen(
                    ["osascript", "-e", f'display notification "{message}" with title "Wyckoff 读盘室"'],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            else:
                subprocess.Popen(
                    ["notify-send", "Wyckoff 读盘室", message],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
        except FileNotFoundError:
            print("\a", end="", flush=True)

    def _chatlog_save(self, role: str, content: str, **kwargs):
        """保存一条对话记录到 SQLite（静默失败）。"""
        try:
            from integrations.local_db import save_chat_log

            save_chat_log(self._session_id, role, content, **kwargs)
        except Exception:
            logger.debug("chat log save failed", exc_info=True)

    def _prepare_turn_memory_context(self) -> tuple[int, str]:
        if not self._messages:
            return -1, ""
        turn_index = len(self._messages) - 1
        user_text = self._messages[turn_index].get("content", "")
        memory_context = self._messages[turn_index].pop("_memory_context", "")
        if not memory_context:
            return turn_index, user_text
        try:
            from cli.memory import prepend_memory_context

            self._messages[turn_index]["_raw_content"] = user_text
            self._messages[turn_index]["content"] = prepend_memory_context(user_text, memory_context)
        except Exception:
            logger.debug("memory context prepend failed", exc_info=True)
        return turn_index, user_text

    def _restore_turn_user_message(self, turn_index: int) -> None:
        if turn_index < 0 or turn_index >= len(self._messages):
            return
        msg = self._messages[turn_index]
        if msg.get("role") == "user" and msg.get("_raw_content"):
            msg["content"] = msg.pop("_raw_content")

    def _create_scratchpad(self, user_text: str) -> AgentScratchpad | None:
        try:
            return AgentScratchpad(user_text, session_id=self._session_id)
        except Exception:
            return None

    # ----- Agent 执行（后台 Worker）-----

    @work(thread=True, exclusive=True)
    def _run_agent(self) -> None:
        self._busy = True
        self._cancel_event.clear()
        log = self.query_one("#chat-log", ChatLog)

        def _write(renderable):
            self.call_from_thread(log.write, renderable)

        def _write_stream(renderable) -> int:
            return self.call_from_thread(_write_counted, log, renderable)

        def _scroll():
            self.call_from_thread(log.scroll_end, animate=False)

        def _spinner_start(label="思考中"):
            self.call_from_thread(self._start_spinner, label)

        def _spinner_stop():
            self.call_from_thread(self._stop_spinner)

        t_start = time.monotonic()

        # 记录用户输入
        _turn_user_index, _user_text = self._prepare_turn_memory_context()
        _scratchpad = self._create_scratchpad(_user_text)
        _workflow_run_id = ""
        _workflow_name = ""
        _model_name = getattr(self._provider, "name", "") if self._provider else ""
        _provider_name = self._state.get("provider_name", "") if self._state else ""
        executed_tool_summaries: list[dict[str, object]] = []
        round_usages: dict[int, dict[str, Any]] = {}
        round_tool_names: dict[int, list[str]] = {}
        round_starts: dict[int, float] = {}
        final_text = ""
        final_usage: dict[str, int] = {"input_tokens": 0, "output_tokens": 0}
        final_elapsed = 0.0
        final_rounds = 0
        last_usage: dict[str, Any] = {}
        self._agent_log.info("session=%s user: %s", self._session_id, _user_text[:200])
        _chatlog_save = self._chatlog_save  # bound method ref

        _stream_separator_strips = 0
        _stream_text_strips = 0
        _streaming_started = False
        _stream_line_buf = ""

        def _ensure_round(round_number: int) -> None:
            if round_number > 0:
                round_starts.setdefault(round_number, time.monotonic())

        def _flush_stream_line() -> None:
            nonlocal _stream_line_buf, _stream_text_strips
            if _stream_line_buf:
                _stream_text_strips += _write_stream(Text(_stream_line_buf))
                _stream_line_buf = ""
                _scroll()

        def _clear_streamed_block(*, include_separator: bool) -> None:
            nonlocal _stream_separator_strips
            nonlocal _stream_text_strips, _streaming_started
            strip_count = _stream_text_strips
            if include_separator:
                strip_count += _stream_separator_strips
            if _streaming_started and strip_count > 0:
                self.call_from_thread(_pop_lines, log, strip_count)
            _stream_text_strips = 0
            if include_separator:
                _stream_separator_strips = 0
                _streaming_started = False

        def _display_tool_result(event: dict[str, Any]) -> None:
            name = event["name"]
            args = event.get("args", {})
            display = self._tools.display_name(name) if self._tools else name
            result = event.get("result")
            if result is None and event.get("error"):
                result = {"error": event["error"]}
            elapsed_s = float(event.get("elapsed_ms", 0)) / 1000

            if isinstance(result, dict) and result.get("error"):
                executed_tool_summaries.append(
                    {
                        "name": name,
                        "args_brief": str(args)[:100],
                        "status": "error",
                        "error": str(result.get("error", ""))[:160],
                    }
                )
                _write(
                    Text.from_markup(
                        f"  [red]✗ {display}[/red] [dim]{elapsed_s:.1f}s {str(result['error'])[:80]}[/dim]"
                    )
                )
            elif isinstance(result, dict) and result.get("status") == "background":
                executed_tool_summaries.append(
                    {
                        "name": name,
                        "args_brief": str(args)[:100],
                        "status": "background",
                    }
                )
                _write(Text.from_markup(f"  [cyan]↗ {display}[/cyan] [dim]已提交后台[/dim]"))
            else:
                executed_tool_summaries.append(
                    {
                        "name": name,
                        "args_brief": str(args)[:100],
                        "status": event.get("status", "ok"),
                    }
                )
                _write(Text.from_markup(f"  [green]✓ {display}[/green] [dim]{elapsed_s:.1f}s[/dim]"))
            _scroll()

        def _display_workflow_plan(event: dict[str, Any]) -> None:
            nonlocal _workflow_run_id, _workflow_name
            _workflow_run_id = str(event.get("run_id", ""))
            _workflow_name = str(event.get("workflow", ""))
            label = str(event.get("label") or _workflow_name)
            steps = event.get("plan", {}).get("steps", [])
            _write(
                Text.from_markup(
                    f"  [bold cyan]workflow[/bold cyan] [dim]{escape(label)} · {escape(_workflow_run_id)}[/dim]"
                )
            )
            for idx, step in enumerate(steps, start=1):
                title = escape(str(step.get("title", "")))
                _write(Text.from_markup(f"    [dim]{idx}.[/dim] {title} [dim]pending[/dim]"))
            _scroll()

        def _display_workflow_step(event: dict[str, Any]) -> None:
            step = event.get("step", {})
            status = step.get("status", "")
            mark = {"running": "→", "completed": "✓", "failed": "✗", "skipped": "·"}.get(status, "·")
            color = {"running": "yellow", "completed": "green", "failed": "red", "skipped": "dim"}.get(status, "dim")
            title = escape(str(step.get("title", "")))
            summary = escape(str(step.get("summary", "")))
            _write(Text.from_markup(f"    [{color}]{mark} {title}[/{color}] [dim]{summary}[/dim]"))
            _scroll()

        def _build_rounds_detail(rounds: int) -> list[dict[str, object]]:
            details: list[dict[str, object]] = []
            for round_number in range(1, rounds + 1):
                usage = round_usages.get(round_number, {})
                started = round_starts.get(round_number, t_start)
                details.append(
                    {
                        "round": round_number,
                        "model": _model_name,
                        "tokens_in": usage.get("input_tokens", 0),
                        "tokens_out": usage.get("output_tokens", 0),
                        "cache_read": usage.get("cache_read_tokens", 0),
                        "cache_write": usage.get("cache_write_tokens", 0),
                        "duration": round(max(0.0, time.monotonic() - started), 2),
                        "has_tool_calls": bool(round_tool_names.get(round_number)),
                        "tool_names": round_tool_names.get(round_number, []),
                    }
                )
            return details

        try:
            if not self._provider or not self._tools:
                raise RuntimeError("模型或工具未初始化")

            # Sub-agent 实时进度回调
            _sub_buf = ""

            def _on_sub_agent_progress(event):
                nonlocal _sub_buf
                agent = event.get("sub_agent", "sub")
                etype = event.get("type")
                if etype == "text_delta":
                    _sub_buf += event.get("text", "")
                    while "\n" in _sub_buf:
                        line, _sub_buf = _sub_buf.split("\n", 1)
                        if line.strip():
                            _write(Text.from_markup(f"    [dim italic]{agent}: {line}[/dim italic]"))
                            _scroll()
                elif etype == "tool_start":
                    name = self._tools.display_name(event["name"]) if self._tools else event["name"]
                    _spinner_start(f"{agent} → {name}")
                elif etype in ("tool_result", "tool_error"):
                    _spinner_stop()
                    name = self._tools.display_name(event["name"]) if self._tools else event["name"]
                    elapsed = event.get("elapsed_ms", 0) / 1000
                    mark = "[green]✓[/green]" if event.get("status") != "error" else "[red]✗[/red]"
                    _write(Text.from_markup(f"    {mark} [dim]{agent} → {name} {elapsed:.1f}s[/dim]"))
                    _scroll()
                elif etype == "done":
                    _spinner_stop()
                    if _sub_buf.strip():
                        _write(Text.from_markup(f"    [dim italic]{agent}: {_sub_buf.strip()}[/dim italic]"))
                        _sub_buf = ""
                    _scroll()

            self._tools._tool_context.on_progress = _on_sub_agent_progress
            self._tools._tool_context.cancel_check = self._cancel_event.is_set

            runtime, workflow_context = build_turn_runtime(
                self._provider,
                self._tools,
                session_id=self._session_id,
                user_text=_user_text,
                scratchpad=_scratchpad,
                cancel_check=self._cancel_event.is_set,
            )
            _workflow_name = "" if workflow_context.is_general else workflow_context.name
            for event in runtime.run_stream(self._messages, with_current_time(self._system_prompt)):
                if self._cancel_event.is_set():
                    _spinner_stop()
                    _flush_stream_line()
                    _write(Text.from_markup("[yellow]⏹ 已中断[/yellow]"))
                    _scroll()
                    while self._messages and self._messages[-1].get("role") != "user":
                        self._messages.pop()
                    if self._messages:
                        self._messages.pop()
                    break

                event_type = event.get("type")
                round_number = int(event.get("round") or 0)
                _ensure_round(round_number)

                if event_type == "workflow_plan":
                    _display_workflow_plan(event)
                    continue

                if event_type in {"workflow_step_start", "workflow_step_done"}:
                    _display_workflow_step(event)
                    continue

                if event_type == "workflow_done":
                    continue

                if event_type == "compaction":
                    before, after = event["before_messages"], event["after_messages"]
                    from rich.panel import Panel

                    panel = Panel(
                        Text.assemble(
                            (" ⚡ 系统状态：上下文深度压缩中...\n\n", "bold yellow"),
                            ("已自动提取持久偏好写入 ", "dim white"),
                            ("SQLite 记忆库", "bold cyan"),
                            ("；\n已将前序 ", "dim white"),
                            (str(before), "bold red"),
                            (" 条陈旧对话压缩为结构化摘要，仅保留最近 ", "dim white"),
                            (str(after), "bold green"),
                            (" 条消息以维持当前上下文连贯性。", "dim white"),
                        ),
                        border_style="yellow",
                        title="[bold yellow] 📦 CONTEXT COMPACTION [/bold yellow]",
                        title_align="left",
                        padding=(1, 2),
                    )
                    _write(panel)
                    _scroll()
                    continue

                if event_type == "thinking_delta":
                    continue

                if event_type == "text_delta":
                    _stream_line_buf += event["text"]
                    if not _streaming_started:
                        _spinner_stop()
                        _stream_separator_strips += _write_stream(Text.from_markup("  [dim]───[/dim]"))
                        _streaming_started = True
                    while "\n" in _stream_line_buf:
                        line, _stream_line_buf = _stream_line_buf.split("\n", 1)
                        _stream_text_strips += _write_stream(Text(line))
                        _scroll()
                    continue

                if event_type == "tool_calls":
                    _flush_stream_line()
                    _clear_streamed_block(include_separator=True)
                    names = [call["name"] for call in event.get("tool_calls", [])]
                    if round_number:
                        round_tool_names.setdefault(round_number, []).extend(names)
                    continue

                if event_type == "usage":
                    usage = event.get("usage", {})
                    if round_number:
                        round_usages[round_number] = usage
                    last_usage = usage
                    fb_msg = getattr(self._provider, "last_fallback_msg", None)
                    if fb_msg:
                        _write(Text.from_markup(f"  [yellow]⚡ {fb_msg}[/yellow]"))
                        self._provider.last_fallback_msg = None
                    continue

                if event_type == "thinking":
                    _spinner_stop()
                    preview = _build_thinking_preview(event.get("text", ""))
                    if preview:
                        _write(preview)
                    continue
                if event_type == "model_start":
                    _spinner_start("思考中")
                    continue

                if event_type == "tool_start":
                    _flush_stream_line()
                    _clear_streamed_block(include_separator=True)
                    display = self._tools.display_name(event["name"]) if self._tools else event["name"]
                    _spinner_start(display)
                    continue

                if event_type in {"tool_result", "tool_error"}:
                    _spinner_stop()
                    _display_tool_result(event)
                    continue

                if event_type == "retry":
                    _flush_stream_line()
                    _clear_streamed_block(include_separator=True)
                    self._agent_log.info(
                        "session=%s loop_guard retry=%d required_tool=%s",
                        self._session_id,
                        event.get("retry", 0),
                        event.get("required_tool", ""),
                    )
                    _write(Text.from_markup("  [yellow]⚠ 模型未执行必需工具，已自动要求继续执行[/yellow]"))
                    _scroll()
                    _spinner_start()
                    continue

                if event_type == "done":
                    _spinner_stop()
                    _flush_stream_line()
                    final_text = event.get("text", "")
                    final_usage = event.get("usage", final_usage)
                    final_elapsed = float(event.get("elapsed", time.monotonic() - t_start))
                    final_rounds = int(event.get("rounds", 0))

                    if _display_final_response(
                        log,
                        final_text,
                        streaming_started=_streaming_started,
                        stream_separator_strips=_stream_separator_strips,
                        stream_text_strips=_stream_text_strips,
                        write=_write,
                        call_from_thread=self.call_from_thread,
                    ):
                        _stream_separator_strips = _stream_text_strips = 0
                        _streaming_started = False
                        _scroll()

                    total_input = final_usage.get("input_tokens", 0)
                    total_output = final_usage.get("output_tokens", 0)
                    self._session_tokens["input"] += total_input
                    self._session_tokens["output"] += total_output
                    self._session_tokens["rounds"] += 1

                    usage_parts = []
                    if total_input or total_output:
                        usage_parts.append(f"↑{total_input:,} ↓{total_output:,}")
                    usage_parts.append(f"{final_elapsed:.1f}s")
                    _write(Text.from_markup(f"  [dim]{' · '.join(usage_parts)}[/dim]"))
                    _scroll()
                    self.call_from_thread(self._update_status)
                    self._restore_turn_user_message(_turn_user_index)

                    _chatlog_save("user", _user_text, model=_model_name, provider=_provider_name)
                    _tc_json = (
                        json.dumps(executed_tool_summaries, ensure_ascii=False) if executed_tool_summaries else ""
                    )
                    _metadata = {
                        "cache_read": last_usage.get("cache_read_tokens", 0),
                        "cache_write": last_usage.get("cache_write_tokens", 0),
                        "stop_reason": last_usage.get("stop_reason", "stop"),
                        "rounds": final_rounds,
                        "rounds_detail": _build_rounds_detail(final_rounds),
                        "messages": list(self._messages),
                        "system_prompt": self._system_prompt,
                        "tools": self._tools.schemas() if self._tools else [],
                        "scratchpad_path": str(_scratchpad.path) if _scratchpad else "",
                        "workflow": _workflow_name,
                        "workflow_run_id": _workflow_run_id,
                    }
                    _chatlog_save(
                        "assistant",
                        final_text,
                        model=_model_name,
                        provider=_provider_name,
                        tokens_in=total_input,
                        tokens_out=total_output,
                        elapsed_s=round(final_elapsed, 2),
                        tool_calls_json=_tc_json,
                        metadata_json=json.dumps(_metadata, ensure_ascii=False),
                    )
                    self._agent_log.info(
                        "session=%s done in=%.1fs tokens=%d/%d",
                        self._session_id,
                        final_elapsed,
                        total_input,
                        total_output,
                    )
                    break

        except AgentCancelled:
            _spinner_stop()
            _flush_stream_line()
            _write(Text.from_markup("[yellow]⏹ 已中断[/yellow]"))
            _scroll()
            while self._messages and self._messages[-1].get("role") != "user":
                self._messages.pop()
            if self._messages:
                self._messages.pop()

        except Exception as e:
            self._restore_turn_user_message(_turn_user_index)
            _spinner_stop()
            err = _friendly_error(e)
            if _scratchpad:
                _scratchpad.record_error(f"{type(e).__name__}: {err}", elapsed_s=time.monotonic() - t_start)
            _write(Text.from_markup(f"[red]错误: {err}[/red]"))
            _elapsed = time.monotonic() - t_start
            self._agent_log.error(
                "session=%s error after=%.1fs type=%s msg=%s",
                self._session_id,
                _elapsed,
                type(e).__name__,
                str(e)[:500],
            )
            _chatlog_save("user", _user_text, model=_model_name, provider=_provider_name)
            _chatlog_save(
                "error",
                "",
                model=_model_name,
                provider=_provider_name,
                elapsed_s=round(_elapsed, 2),
                error=f"{type(e).__name__}: {str(e)[:500]}",
            )
            while self._messages and self._messages[-1].get("role") != "user":
                self._messages.pop()
            if self._messages:
                self._messages.pop()

        finally:
            self._busy = False
            if self._tools:
                self._tools._tool_context.on_progress = None
            if self._queue:
                next_msg = self._queue.popleft()
                self.call_from_thread(self._send_message, next_msg)

    # ----- 后台任务回调 -----

    def _on_bg_progress(self, _task) -> None:
        """后台线程报进度 → 刷新面板。"""
        try:
            self.call_from_thread(self._refresh_bg_panel)
        except Exception:
            logger.debug("background panel refresh failed", exc_info=True)

    def _refresh_bg_panel(self) -> None:
        self.query_one("#bg-panel", BackgroundTaskPanel)._tick()

    def _on_bg_complete(self, task_id: str, tool_name: str, result) -> None:
        """后台任务完成，注入结果到消息队列。"""
        from cli.tools import TOOL_DISPLAY_NAMES

        display = TOOL_DISPLAY_NAMES.get(tool_name, tool_name)
        is_error = isinstance(result, dict) and result.get("error")

        try:
            from integrations.local_db import save_background_task_result

            save_background_task_result(
                task_id,
                tool_name,
                result,
                session_id=self._session_id,
                status="failed" if is_error else "completed",
            )
        except Exception:
            logger.debug("save background task result failed", exc_info=True)

        log = self.query_one("#chat-log", ChatLog)
        if is_error:
            self.call_from_thread(
                log.write,
                Text.from_markup(f"  [red]✗ 后台任务失败：{display}[/red] [dim]{str(result['error'])[:80]}[/dim]"),
            )
        else:
            self.call_from_thread(
                log.write,
                Text.from_markup(f"  [green]✅ 后台任务完成：{display}[/green]"),
            )

        summary_str = json.dumps(result, ensure_ascii=False, default=str)
        if len(summary_str) > 3000:
            summary_str = summary_str[:3000] + "..."

        notification = (
            "[SYSTEM NOTIFICATION - NOT USER INPUT]\n"
            "This is an automated background-task event, NOT a message from the user.\n"
            "Do NOT interpret this as user acknowledgement, confirmation, or response to any pending question.\n\n"
            "<system-reminder>\n"
            "<task-notification>\n"
            f"<task-id>{task_id}</task-id>\n"
            f"<tool-name>{tool_name}</tool-name>\n"
            f"<status>{'failed' if is_error else 'completed'}</status>\n"
            f"<summary>{summary_str}</summary>\n"
            "</task-notification>\n"
            "</system-reminder>"
        )
        self._queue.append(notification)
        # 空闲时自动触发
        if not self._busy:
            self.call_from_thread(self._send_message, self._queue.popleft())

    # ----- Actions -----

    def action_clear_chat(self) -> None:
        self.query_one("#chat-log", ChatLog).clear()

    def action_resume_session(self) -> None:
        self._resume_session_selector()

    def action_export_session(self) -> None:
        from cli.session_tools import SessionToolError, export_session_transcript

        log = self.query_one("#chat-log", ChatLog)
        try:
            result = export_session_transcript(session_id=self._session_id)
        except SessionToolError as exc:
            log.write(Text.from_markup(f"[red]导出失败: {exc}[/red]"))
            return
        log.write(Text.from_markup(f"[green]✓ 会话已导出[/green] [dim]{result.path}[/dim]"))

    def action_fork_session(self) -> None:
        from cli.session_tools import SessionToolError, fork_session

        log = self.query_one("#chat-log", ChatLog)
        self._save_memory_async()
        try:
            result = fork_session(session_id=self._session_id)
        except SessionToolError as exc:
            log.write(Text.from_markup(f"[red]分叉失败: {exc}[/red]"))
            return
        log.write(
            Text.from_markup(
                f"[green]✓ 会话已分叉[/green] [dim]{result.source_session_id} → {result.new_session_id}[/dim]"
            )
        )
        self._resume_session(result.new_session_id)

    def _resume_session_selector(self) -> None:
        """弹出选择器，选择要恢复的历史会话。"""
        from integrations.local_db import get_session_preview, list_chat_sessions

        log = self.query_one("#chat-log", ChatLog)
        sessions = list_chat_sessions(limit=20)
        sessions = [s for s in sessions if s["session_id"] != self._session_id]
        if not sessions:
            log.write(Text.from_markup("[dim]没有可恢复的历史会话[/dim]"))
            return
        options = []
        for s in sessions:
            preview = get_session_preview(s["session_id"])
            started = (s["started_at"] or "?")[:16]
            n = s["msg_count"]
            label = f"{started}  ({n}条)  {preview}"
            options.append((s["session_id"], label))
        self._show_selector(options, "session_resume")

    def _resume_session(self, session_id: str) -> None:
        """恢复指定会话，加载历史消息到 self._messages。"""
        from integrations.local_db import list_chat_sessions, load_chat_logs

        log = self.query_one("#chat-log", ChatLog)

        if session_id.isdigit():
            idx = int(session_id)
            sessions = list_chat_sessions(limit=20)
            sessions = [s for s in sessions if s["session_id"] != self._session_id]
            if idx < 1 or idx > len(sessions):
                log.write(Text.from_markup(f"[red]无效序号: {idx} (共 {len(sessions)} 个历史会话)[/red]"))
                return
            session_id = sessions[idx - 1]["session_id"]

        rows = load_chat_logs(session_id=session_id)
        if not rows:
            log.write(Text.from_markup(f"[red]未找到会话: {session_id}[/red]"))
            return

        # 保存当前会话记忆
        self._save_memory_async()

        self._messages.clear()
        self._queue.clear()
        self._session_tokens = {"input": 0, "output": 0, "rounds": 0}
        self._session_id = session_id
        self._update_status()
        log.clear()

        log.write(Text.from_markup(f"[green]已恢复会话[/green] [dim]{session_id} · {len(rows)} 条记录[/dim]\n"))

        for row in rows:
            role = row["role"]
            content = row["content"] or ""

            if role == "error":
                if row.get("error"):
                    log.write(Text.from_markup(f"  [dim red]✗ {str(row['error'])[:80]}[/dim red]"))
                continue

            if role == "user":
                self._messages.append({"role": "user", "content": content})
                preview = content if len(content) <= 120 else content[:120] + "…"
                log.write(Text.from_markup(f"[bold cyan]❯[/bold cyan] {preview}"))

            elif role == "assistant":
                self._messages.append({"role": "assistant", "content": content})
                tc = row.get("tool_calls", "")
                if tc:
                    try:
                        calls = json.loads(tc)
                        names = ", ".join(c.get("name", "?") for c in calls)
                        log.write(Text.from_markup(f"  [dim green]✓ {names}[/dim green]"))
                    except (json.JSONDecodeError, TypeError):
                        pass
                if content:
                    preview = content if len(content) <= 200 else content[:200] + "…"
                    log.write(Text.from_markup(f"  [dim]{preview}[/dim]"))

        log.write(Text.from_markup("\n[dim]───── 历史消息结束，继续对话 ─────[/dim]\n"))
        log.scroll_end(animate=False)
        self._update_status()

    def action_new_chat(self) -> None:
        # 保存会话记忆
        self._save_memory_async()
        self._messages.clear()
        self._queue.clear()
        self._session_tokens = {"input": 0, "output": 0, "rounds": 0}
        self._session_id = uuid.uuid4().hex[:12]
        log = self.query_one("#chat-log", ChatLog)
        log.clear()
        log.write(Text.from_markup("[green]新对话已开始[/green]\n"))
        self._update_status()


# 注册命令面板（class 定义完成后）
try:
    from cli.commands import WyckoffCommands

    WyckoffTUI.COMMANDS = {WyckoffCommands}
except ImportError:
    pass


def _brief_args(args: dict) -> str:
    if not args:
        return ""
    s = ", ".join(f"{k}={v}" for k, v in args.items())
    return s[:60] + ("..." if len(s) > 60 else "")
