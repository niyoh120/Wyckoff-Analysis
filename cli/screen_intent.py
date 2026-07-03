"""Shared helpers for stock-screen intent arguments."""

from __future__ import annotations

from core.theme_radar import THEME_ALIASES

_BOARD_HINTS = (
    (
        "main_chinext_star",
        (
            "主板+创业板",
            "主板和创业板",
            "主板创业板科创",
            "主板创业板科创板",
            "主板+创业板+科创",
            "主板+创业板+科创板",
            "主板和创业板和科创",
            "主板和创业板和科创板",
            "主板+科创板",
            "主板和科创板",
            "主板+科创",
            "主板和科创",
            "创业板+科创板",
            "创业板和科创板",
            "创业板+科创",
            "创业板和科创",
            "沪深a",
            "沪深 a",
            "沪深a股",
            "沪深 a股",
            "沪深a 股",
            "不含北交",
            "非北交",
            "排除北交",
            "剔除北交",
            "双创",
            "主创",
            "main_chinext",
            "main-chinext",
            "main+chinext",
        ),
    ),
    ("chinext", ("创业板", "创板", "gem", "chinext")),
    ("star", ("科创板", "科创", "star")),
    ("bse", ("北交所", "北交", "bse")),
    ("main", ("沪深主板", "主板", "main")),
    ("all", ("a股", "a 股", "全a", "全 a", "全市场", "全量", "全部", "所有", "all")),
)

_STYLE_HINTS = (
    ("trend", ("强势", "趋势", "右侧", "突破", "主升", "最强", "领涨", "龙头", "强度", "短线", "起爆")),
    ("pullback", ("低吸", "吸筹", "左侧", "回踩", "埋伏")),
    (
        "quality",
        (
            "稳健",
            "稳一点",
            "稳点",
            "高质量",
            "质量",
            "安全",
            "安全点",
            "低风险",
            "风险低",
            "风险小",
            "波动小",
            "别太激进",
            "不激进",
            "保守",
            "防守",
            "基本面好",
            "财务好",
            "业绩好",
            "盈利好",
            "盈利能力",
            "roe高",
            "roe 高",
            "低估值",
            "估值合理",
            "红利",
            "高股息",
            "股息",
            "分红",
            "高分红",
            "现金流",
            "价值",
            "蓝筹",
            "低波",
        ),
    ),
)

_FULL_SCAN_HINTS = (
    "全量",
    "完整扫描",
    "完整筛选",
    "完整复核",
    "正式扫描",
    "正式筛选",
    "正式复核",
    "跑完整",
)

_FINANCIAL_METRICS_ON_HINTS = (
    "财务过滤",
    "财务指标",
    "财务数据",
    "基本面",
    "财报",
    "财务好",
    "业绩",
    "盈利",
    "roe",
    "低估值",
    "估值合理",
    "估值",
    "毛利",
    "净利",
    "红利",
    "高股息",
    "股息",
    "分红",
    "高分红",
    "现金流",
    "价值",
    "蓝筹",
    "低波",
)

_FINANCIAL_METRICS_OFF_HINTS = (
    "快扫",
    "快速扫",
    "快速筛",
    "粗扫",
    "先扫",
    "先筛",
)

_TEMPORAL_BUY_CONTEXT_HINTS = (
    "今天",
    "今日",
    "明天",
    "明日",
    "现在",
    "当前",
    "盘中",
    "尾盘",
    "早盘",
    "午后",
    "下午",
    "最近",
    "近期",
    "本周",
    "这周",
)

_TEMPORAL_BUY_ACTION_HINTS = (
    "买啥",
    "买什么",
    "买哪",
    "买哪个",
    "能买啥",
    "能买什么",
    "可买啥",
    "可买什么",
    "可以买啥",
    "可以买什么",
)

_WATCH_OBJECT_CONTEXT_HINTS = (
    "a股",
    "a 股",
    "股票",
    "股",
    "票",
    "标的",
    "市场",
    "大盘",
    "盘面",
    "板块",
    "行业",
    "方向",
    "机会",
    "机会池",
)

_WATCH_TRADING_CONTEXT_HINTS = (
    "盘中",
    "尾盘",
    "早盘",
    "午后",
)

_WATCH_ACTION_HINTS = (
    "看啥",
    "看什么",
    "看哪些",
    "关注啥",
    "关注什么",
    "关注哪些",
    "跟踪啥",
    "跟踪什么",
    "跟踪哪些",
)

_CANDIDATE_REQUEST_TARGET_HINTS = (
    "候选股",
    "股票",
    "标的",
    "候选",
    "票",
)

_CANDIDATE_REQUEST_ACTION_HINTS = (
    "给我几只",
    "给我几个",
    "给几只",
    "给几个",
    "来几只",
    "来几个",
    "找几只",
    "找几个",
    "挑几只",
    "挑几个",
    "推荐几只",
    "推荐几个",
    "筛几只",
    "筛几个",
    "有什么",
    "有啥",
    "有哪些",
    "哪几个",
    "哪几只",
)

_STYLE_TARGET_HINTS = (
    "股票",
    "股",
    "票",
    "标的",
    "候选",
    "机会",
    "板块",
    "方向",
)

_NON_STOCK_TICKET_HINTS = (
    "电影票",
    "门票",
    "机票",
    "车票",
    "彩票",
    "发票",
    "票据",
    "选票",
)


def stock_screen_suggested_args(text: str, *, include_default_board: bool = True) -> dict[str, str]:
    """Infer simple screen_stocks arguments from user wording."""

    payload: dict[str, str] = {}
    board = stock_screen_board_hint(text)
    if board or include_default_board:
        payload["board"] = board or "all"
    if style := stock_screen_style_hint(text):
        payload["style"] = style
    if limit := stock_screen_limit_hint(text):
        payload["limit"] = limit
    if financial_metrics := stock_screen_financial_metrics_hint(text):
        payload["financial_metrics"] = financial_metrics
    if theme := stock_screen_theme_hint(text):
        payload["theme"] = theme
    return payload


def stock_screen_board_hint(text: str) -> str:
    normalized = _normalize_text(text)
    for board, hints in _BOARD_HINTS:
        if any(hint in normalized for hint in hints):
            return board
    return ""


def stock_screen_style_hint(text: str) -> str:
    normalized = _normalize_text(text)
    styles = [style for style, hints in _STYLE_HINTS if any(hint in normalized for hint in hints)]
    return ",".join(dict.fromkeys(styles))


def stock_screen_style_target_hint(text: str) -> bool:
    normalized = _normalize_text(text)
    return bool(stock_screen_style_hint(normalized)) and any(hint in normalized for hint in _STYLE_TARGET_HINTS)


def stock_screen_limit_hint(text: str) -> str:
    normalized = _normalize_text(text)
    return "0" if any(hint in normalized for hint in _FULL_SCAN_HINTS) else ""


def stock_screen_financial_metrics_hint(text: str) -> str:
    normalized = _normalize_text(text)
    if any(hint in normalized for hint in _FINANCIAL_METRICS_ON_HINTS):
        return "true"
    if any(hint in normalized for hint in _FINANCIAL_METRICS_OFF_HINTS):
        return "false"
    return ""


def stock_screen_theme_hint(text: str) -> str:
    normalized = _normalize_text(text)
    for theme, aliases in THEME_ALIASES.items():
        terms = (theme, *aliases)
        if any(term and term.lower() in normalized for term in terms):
            return theme
    return ""


def stock_screen_temporal_buy_hint(text: str) -> bool:
    normalized = _normalize_text(text)
    return any(hint in normalized for hint in _TEMPORAL_BUY_CONTEXT_HINTS) and any(
        hint in normalized for hint in _TEMPORAL_BUY_ACTION_HINTS
    )


def stock_screen_watch_hint(text: str) -> bool:
    normalized = _normalize_text(text)
    if not any(hint in normalized for hint in _WATCH_ACTION_HINTS):
        return False
    return any(hint in normalized for hint in _WATCH_OBJECT_CONTEXT_HINTS) or any(
        hint in normalized for hint in _WATCH_TRADING_CONTEXT_HINTS
    )


def stock_screen_candidate_request_hint(text: str) -> bool:
    normalized = _normalize_text(text)
    if any(hint in normalized for hint in _NON_STOCK_TICKET_HINTS):
        return False
    return any(hint in normalized for hint in _CANDIDATE_REQUEST_TARGET_HINTS) and any(
        hint in normalized for hint in _CANDIDATE_REQUEST_ACTION_HINTS
    )


def _normalize_text(text: str) -> str:
    return str(text or "").strip().lower()
