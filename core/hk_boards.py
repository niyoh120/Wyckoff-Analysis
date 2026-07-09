"""HK-share board classification helpers.

HK stock codes follow ``NNNNN.HK`` format (5-digit number + ``.HK`` suffix).
Board membership is determined by the numeric prefix:
  - 0xxxx / 1xxxx / 2xxxx / 3xxxx / 4xxxx / 5xxxx / 6xxxx / 7xxxx / 8xxxx / 9xxxx → main board
  - 8xxxx where the numeric part < 8000 is historically GEM-listed
    (GEM codes were migrated to main-board 5-digit format in 2008;
     current GEM stocks have been reassigned, so we rely on an
     explicit GEM set loaded from ``data/market_universes/hk_gem.txt`` if available).

In practice the distinction that matters most for Wyckoff analysis is
*main-board liquid* vs *illiquid micro-cap*; the latter is already
filtered by ``min_quote_amount`` / ``min_quote_price`` at the data layer.
"""

from __future__ import annotations

from pathlib import Path

from core.wyckoff_engine import FunnelConfig

_GEM_CODES: set[str] | None = None
_GEM_FILE = Path(__file__).resolve().parents[1] / "data" / "market_universes" / "hk_gem.txt"


def _load_gem_codes() -> set[str]:
    if not _GEM_FILE.exists():
        return set()
    codes: set[str] = set()
    for line in _GEM_FILE.read_text(encoding="utf-8").splitlines():
        clean = line.split("#", 1)[0].strip().upper()
        if clean:
            codes.add(clean)
    return codes


def hk_board(code: object) -> str:
    """Return board classification for an HK stock code.

    Returns one of: ``"main"``, ``"gem"``, ``"foreign"``, ``"unknown"``.
    """
    text = str(code or "").strip().upper()
    if text.endswith(".HK"):
        num = text[:-3]
    else:
        num = text

    if not num or not num.isdigit():
        return "unknown"

    global _GEM_CODES
    if _GEM_CODES is None:
        _GEM_CODES = _load_gem_codes()

    if text in (_GEM_CODES or set()):
        return "gem"

    if len(num) == 5 and num.startswith("8") and int(num) < 8000:
        return "gem"

    return "main"


def is_hk_main_board(code: object) -> bool:
    return hk_board(code) == "main"


def is_hk_gem(code: object) -> bool:
    return hk_board(code) == "gem"


def apply_hk_funnel_cfg(cfg: FunnelConfig, *, min_avg_amount: float = 0.0) -> None:
    """港股漏斗参数调优——集中一处，供漏斗任务和回测网格共用。

    核心差异：
    - 无涨跌停：SOS/Spring 日内波幅可远超 A 股，阈值需提高以防财技假突破。
    - 仙股/老千股：成交额尾部极度稀薄，日均额门槛必须抬高。
    - 南向驱动：龙头长期偏离年线是常态（腾讯、比亚迪），bias_200 需放宽。
    - 做空机制：放量下跌可能是空头平仓而非派发，EVR 换手门槛放宽。
    - GEM 板块：流动性极差，吸筹通道需收严避免误判老千股横盘。
    """
    # SOS：无涨跌停下假突破更多，7% + 3 倍量能过滤财技拉抬
    cfg.sos_pct_min = 7.0
    cfg.sos_vol_ratio = 3.0
    # Spring：日内振幅可以很大但 25% 以内才算有效回踩（超过多为老千股操纵）
    cfg.spring_tr_max_range_pct = 25.0
    cfg.spring_vol_ratio = 1.5  # 放量确认门槛适度提高，过滤无量假弹
    # 年线偏离：南向龙头长期高偏离是常态
    cfg.global_entry_max_bias_200 = 35.0
    cfg.trend_entry_max_bias_200 = 40.0
    # 吸筹通道：GEM 仙股横盘是陷阱，收严位阶和振幅
    cfg.accum_price_from_low_max = 0.40
    cfg.accum_range_max_pct = 25.0  # 收严：横盘振幅不超过 25%（老千股常 30%+ 振荡洗盘）
    # EVR：做空机制下放量下跌可能是空头回补而非派发，换手门槛放宽
    cfg.evr_min_turnover = 0.3
    cfg.evr_max_rise = 3.0  # 无涨跌停下正常反弹幅度更大
    # LPS：缩量回踩在港股有效性更高（做空盘枯竭后自然缩量），缩量比适度放宽
    cfg.lps_vol_dry_ratio = 0.55
    # RPS：港股结构性行情更极端，RPS 门槛适度降低以捕获南向资金突然涌入的标的
    cfg.rps_fast_min = 60.0
    cfg.rps_slow_min = 65.0
    # RS：港股大盘（恒指）成分股权重极度集中，RS 门槛适度放宽
    cfg.rs_min_long = 1.5
    cfg.rs_min_short = 0.5
    # 地量通道：港股仙股常出现虚假地量（无人交易），收严位阶保护
    cfg.dry_vol_price_from_low_max = 0.30
    # RS 背离通道：港股更容易出现"指数跌但个股不跌"（南向托底），保持启用
    cfg.enable_rs_divergence_channel = True
    cfg.rs_div_price_from_low_max = 0.45
    # 日均成交额：头部集中、尾部极度稀薄，最低 800 万（≈ 800 万港元）
    cfg.min_avg_amount_wan = max(min_avg_amount / 10000.0, 800.0)
    # 收盘价底线：低于 1 港元进入仙股区域，风险门禁已兜底，此处额外加码
    cfg.l1_min_close_price = 1.0
