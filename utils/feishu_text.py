"""Small text helpers shared by Feishu delivery and rich-card builders."""

from __future__ import annotations

import re

_TERM_GLOSSARY_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bBLACK_SWAN\b(?!\s*[（(])"), "BLACK_SWAN（黑天鹅高风险）"),
    (re.compile(r"\bRISK_OFF\b(?!\s*[（(])"), "RISK_OFF（风险收缩）"),
    (re.compile(r"\bRISK_ON\b(?!\s*[（(])"), "RISK_ON（短线过热禁追）"),
    (re.compile(r"\bNORMAL\b(?!\s*[（(])"), "NORMAL（常态）"),
    (re.compile(r"\bPANIC_REPAIR_CONFIRMED\b(?!\s*[（(])"), "PANIC_REPAIR_CONFIRMED（修复成立）"),
    (re.compile(r"\bPANIC_REPAIR\b(?![_\s]*CONFIRMED)(?!\s*[（(])"), "PANIC_REPAIR（修复候选）"),
    (re.compile(r"\bVIX\b(?!\s*[（(])"), "VIX（波动率恐慌指数）"),
    (re.compile(r"\bA50\b(?!\s*[（(])"), "A50（富时中国A50期货）"),
    (re.compile(r"\bATR\b(?!\s*[（(])"), "ATR（真实波动幅度）"),
    (re.compile(r"\bRPS\b(?!\s*[（(])"), "RPS（相对强弱百分位）"),
    (re.compile(r"\bQPS\b(?!\s*[（(])"), "QPS（每秒请求量）"),
    (re.compile(r"\bATTACK\b(?!\s*[（(])"), "ATTACK（进攻建仓）"),
    (re.compile(r"\bPROBE\b(?!\s*[（(])"), "PROBE（试探建仓）"),
    (re.compile(r"\bTRIM\b(?!\s*[（(])"), "TRIM（减仓）"),
    (re.compile(r"\bHOLD\b(?!\s*[（(])"), "HOLD（持有观察）"),
    (re.compile(r"\bEXIT\b(?!\s*[（(])"), "EXIT（清仓离场）"),
    (re.compile(r"\bNO_TRADE\b(?!\s*[（(])"), "NO_TRADE（拒单）"),
    (re.compile(r"\bAPPROVED\b(?!\s*[（(])"), "APPROVED（核准执行）"),
    (re.compile(r"\bComposite Man\b(?!\s*[（(])"), "Composite Man（综合人/主力）"),
    (re.compile(r"\bTape Reading\b(?!\s*[（(])"), "Tape Reading（盘面解读）"),
    (re.compile(r"\bSpring\b(?!\s*[（(])"), "Spring（弹簧/假跌破）"),
    (re.compile(r"\bLPS\b(?!\s*[（(])"), "LPS（最后支撑点）"),
    (re.compile(r"\bSOS\b(?!\s*[（(])"), "SOS（强势信号）"),
    (re.compile(r"\bUTAD\b(?!\s*[（(])"), "UTAD（上冲诱多）"),
    (re.compile(r"\bEVR\b(?!\s*[（(])"), "EVR（放量不跌）"),
    (re.compile(r"\bJAC\b(?!\s*[（(])"), "JAC（跃过小溪）"),
    (re.compile(r"\bBUEC\b(?!\s*[（(])"), "BUEC（回踩小溪边缘）"),
    (re.compile(r"\bStop[- ]?Loss\b(?!\s*[（(])", re.IGNORECASE), "Stop-Loss（止损位）"),
    (re.compile(r"\bEntry\b(?!\s*[（(])", re.IGNORECASE), "Entry（入场区）"),
    (re.compile(r"\bTarget\b(?!\s*[（(])", re.IGNORECASE), "Target（目标位）"),
]


def annotate_financial_terms(content: str) -> str:
    """Add Chinese glosses for common trading terms when they are still bare."""
    if not content:
        return content
    out = content
    for pattern, replacement in _TERM_GLOSSARY_PATTERNS:
        out = pattern.sub(replacement, out)
    return out


_TABLE_SEPARATOR_RE = re.compile(r"^\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?$")


def _is_table_row(stripped: str) -> bool:
    return stripped.startswith("|") and stripped.endswith("|") and stripped.count("|") >= 2


def _split_table_row(stripped: str) -> list[str]:
    return [cell.strip() for cell in stripped.strip("|").split("|")]


def _table_block_to_lines(header: list[str], rows: list[list[str]]) -> list[str]:
    out: list[str] = []
    for row in rows:
        cells = [f"{name}: {row[idx]}" if idx < len(row) else f"{name}: -" for idx, name in enumerate(header)]
        out.append("- " + "，".join(cells))
    return out


def _consume_table(lines: list[str], start: int) -> tuple[list[str], int]:
    header = _split_table_row(lines[start].strip())
    rows: list[list[str]] = []
    idx = start + 2
    while idx < len(lines) and _is_table_row(lines[idx].strip()):
        rows.append(_split_table_row(lines[idx].strip()))
        idx += 1
    return _table_block_to_lines(header, rows), idx


def normalize_lark_md(content: str) -> str:
    safe_content = content.replace("<", "&lt;").replace(">", "&gt;")
    lines = safe_content.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        stripped = line.strip()
        if not stripped:
            out.append("")
            i += 1
            continue
        if stripped.startswith("#"):
            title = stripped.lstrip("#").strip()
            out.append(f"**{title}**" if title else "")
            i += 1
            continue
        if stripped in {"---", "***", "___"}:
            out.append("")
            i += 1
            continue
        if _is_table_row(stripped) and i + 1 < len(lines) and _TABLE_SEPARATOR_RE.match(lines[i + 1].strip()):
            table_lines, i = _consume_table(lines, i)
            out.extend(table_lines)
            continue
        out.append(line)
        i += 1
    return "\n".join(out).strip()


def split_lark_md(content: str, max_len: int = 2800) -> list[str]:
    if len(content) <= max_len:
        return [content]

    paragraphs = content.split("\n\n")
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        candidate = paragraph if not current else f"{current}\n\n{paragraph}"
        if len(candidate) <= max_len:
            current = candidate
            continue
        if current:
            chunks.append(current)
            current = ""
        if len(paragraph) <= max_len:
            current = paragraph
            continue
        start = 0
        while start < len(paragraph):
            chunks.append(paragraph[start : start + max_len])
            start += max_len
    if current:
        chunks.append(current)
    return chunks


def lark_md_div(content: str) -> dict:
    return {"tag": "div", "text": {"tag": "lark_md", "content": content}}


def lark_note(content: str) -> dict:
    return {"tag": "note", "elements": [{"tag": "plain_text", "content": content}]}
