"""A50/VIX risk inputs for the premarket risk workflow."""

from __future__ import annotations

import csv
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from io import StringIO
from zoneinfo import ZoneInfo

import requests

from utils.safe import finite_float

TZ = ZoneInfo("Asia/Shanghai")
US_TZ = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class PremarketRiskConfig:
    a50_crash_pct: float
    a50_risk_off_pct: float
    vix_crash_pct: float
    vix_crash_close: float
    vix_risk_off_pct: float
    vix_ready_hour_et: int
    vix_poll_interval_seconds: int
    vix_max_attempts: int


def premarket_risk_config_from_env() -> PremarketRiskConfig:
    return PremarketRiskConfig(
        a50_crash_pct=float(os.getenv("PREMARKET_A50_CRASH_PCT", "-2.0")),
        a50_risk_off_pct=float(os.getenv("PREMARKET_A50_RISK_OFF_PCT", "-1.0")),
        vix_crash_pct=float(os.getenv("PREMARKET_VIX_CRASH_PCT", "15.0")),
        vix_crash_close=float(os.getenv("PREMARKET_VIX_CRASH_CLOSE", "25.0")),
        vix_risk_off_pct=float(os.getenv("PREMARKET_VIX_RISK_OFF_PCT", "8.0")),
        vix_ready_hour_et=int(os.getenv("PREMARKET_VIX_READY_HOUR_ET", "17")),
        vix_poll_interval_seconds=max(1, int(os.getenv("PREMARKET_VIX_POLL_INTERVAL_SECONDS", "300"))),
        vix_max_attempts=max(int(os.getenv("PREMARKET_VIX_MAX_ATTEMPTS", "12")), 1),
    )


def build_action_matrix(regime: str) -> list[str]:
    if regime == "BLACK_SWAN":
        return [
            "🔒 **盘前动作开关**（BLACK_SWAN）",
            "- ✅ `EXIT`：允许（破位/止损优先执行）",
            "- ✅ `TRIM`：允许（主动降风险）",
            "- ⚠️ `HOLD`：允许（仅守防线，不主观乐观）",
            "- ⛔ `LIGHT_ADD`：禁止",
            "- ⛔ `PROBE`：禁止",
            "- ⛔ `ATTACK`：禁止",
            "- ⛔ `FULL_ATTACK`：禁止",
        ]
    if regime == "CAUTION":
        return [
            "🟠 **盘前动作开关**（CAUTION）",
            "- ✅ `EXIT`：允许",
            "- ✅ `TRIM`：允许",
            "- ✅ `HOLD`：允许（保持防守纪律）",
            "- ⚠️ `LIGHT_ADD`：仅允许对**已有强势浮盈仓位**小幅加仓",
            "- ✅ `PROBE`：允许（仅小仓位试探，盘中需二次确认）",
            "- ⛔ `ATTACK`：默认禁止",
            "- ⛔ `FULL_ATTACK`：禁止",
        ]
    if regime == "RISK_OFF":
        return [
            "🔒 **盘前动作开关**（RISK_OFF）",
            "- ✅ `EXIT`：允许",
            "- ✅ `TRIM`：允许",
            "- ✅ `HOLD`：允许（防守为主）",
            "- ⚠️ `LIGHT_ADD`：仅允许对**已有浮盈仓位**小幅加仓（总权益 <= 5%）",
            "- ⛔ `PROBE`：默认禁止",
            "- ⛔ `ATTACK`：禁止",
            "- ⛔ `FULL_ATTACK`：禁止",
        ]
    return [
        "🔓 **盘前动作开关**（NORMAL）",
        "- ✅ `EXIT`：允许",
        "- ✅ `TRIM`：允许",
        "- ✅ `HOLD`：允许",
        "- ⚠️ `LIGHT_ADD`：条件允许（仅确认强势且量价匹配）",
        "- ⚠️ `PROBE`：条件允许（控制仓位）",
        "- ⚠️ `ATTACK`：条件允许（需盘中二次确认）",
        "- ⛔ `FULL_ATTACK`：默认禁止；仅在强一致 Risk-On 且盘中确认后考虑",
    ]


def fetch_a50() -> dict:
    out = _empty_quote("akshare:futures_global_hist_em(CN00Y)")
    try:
        return _fetch_a50_with_akshare(out)
    except Exception as exc:
        out["error"] = str(exc)
        return out


def fetch_vix(config: PremarketRiskConfig | None = None) -> dict:
    cfg = config or premarket_risk_config_from_env()
    cboe = fetch_vix_cboe(cfg)
    if cboe["ok"]:
        return cboe
    stooq = fetch_vix_stooq(cfg)
    if stooq["ok"]:
        return stooq
    yahoo = fetch_vix_yahoo(cfg)
    if yahoo["ok"]:
        return yahoo
    return {
        "ok": False,
        "source": "cboe+stooq+yahoo",
        "date": None,
        "close": None,
        "pct_chg": None,
        "error": f"cboe={cboe.get('error')}; stooq={stooq.get('error')}; yahoo={yahoo.get('error')}",
    }


def fetch_vix_until_ready(
    *,
    config: PremarketRiskConfig | None = None,
    log: Callable[[str], None] | None = None,
) -> dict:
    cfg = config or premarket_risk_config_from_env()
    logger = log or (lambda _msg: None)
    for attempt in range(1, cfg.vix_max_attempts + 1):
        vix = fetch_vix(cfg)
        if vix.get("ok"):
            logger(f"VIX可用，结束轮询: attempt={attempt}, source={vix.get('source')}, date={vix.get('date')}")
            return vix
        _log_vix_retry(logger, attempt, cfg, vix)
        if attempt < cfg.vix_max_attempts:
            time.sleep(cfg.vix_poll_interval_seconds)
    logger(f"VIX轮询超过最大重试次数({cfg.vix_max_attempts})，使用降级结果")
    return _vix_timeout_fallback(cfg)


def judge_regime(
    a50: dict,
    vix: dict,
    config: PremarketRiskConfig | None = None,
) -> tuple[str, list[str]]:
    cfg = config or premarket_risk_config_from_env()
    reasons: list[str] = []
    regime = "NORMAL"
    a50_pct = finite_float(a50.get("pct_chg"))
    vix_close = finite_float(vix.get("close"))
    vix_pct = finite_float(vix.get("pct_chg"))
    regime = _judge_crash_or_caution(regime, reasons, a50_pct, vix_close, vix_pct, cfg)
    if regime != "BLACK_SWAN":
        regime = _judge_risk_off(regime, reasons, a50_pct, vix_close, vix_pct, cfg)
    if not reasons:
        reasons.append("A50/VIX 未触发风险阈值")
    return regime, reasons


def latest_expected_us_trade_date(config: PremarketRiskConfig, now: datetime | None = None) -> date:
    dt_us = now.astimezone(US_TZ) if now else datetime.now(US_TZ)
    candidate = dt_us.date()
    if dt_us.weekday() < 5 and dt_us.hour >= config.vix_ready_hour_et:
        return candidate
    candidate -= timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate -= timedelta(days=1)
    return candidate


def ensure_vix_fresh(
    raw_date: object,
    source: str,
    config: PremarketRiskConfig,
    now: datetime | None = None,
) -> date:
    trade_date = _parse_trade_date(raw_date)
    if trade_date is None:
        raise RuntimeError(f"{source} date invalid: {raw_date}")
    expected_date = latest_expected_us_trade_date(config, now=now)
    if trade_date < expected_date:
        raise RuntimeError(f"{source} stale: latest={trade_date.isoformat()} < expected={expected_date.isoformat()}")
    return trade_date


def fetch_vix_stooq(config: PremarketRiskConfig) -> dict:
    out = _empty_quote("stooq:^vix")
    try:
        response = requests.get("https://stooq.com/q/d/l/?s=%5Evix&i=d", timeout=8)
        response.raise_for_status()
        rows = list(csv.DictReader(StringIO(response.text)))
        if len(rows) < 2:
            raise RuntimeError("stooq rows<2")
        return _vix_from_close_rows(out, rows[-1].get("Date"), rows[-1].get("Close"), rows[-2].get("Close"), config)
    except Exception as exc:
        out["error"] = str(exc)
        return out


def fetch_vix_cboe(config: PremarketRiskConfig) -> dict:
    out = _empty_quote("cboe:VIX_History.csv")
    try:
        response = requests.get("https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv", timeout=10)
        response.raise_for_status()
        valid = _cboe_valid_rows(list(csv.DictReader(StringIO(response.text))))
        if len(valid) < 2:
            raise RuntimeError("cboe valid close<2")
        return _vix_from_close_rows(out, valid[0][0], valid[0][1], valid[1][1], config)
    except Exception as exc:
        out["error"] = str(exc)
        return out


def fetch_vix_yahoo(config: PremarketRiskConfig) -> dict:
    out = _empty_quote("yahoo:^VIX")
    try:
        response = requests.get(
            "https://query1.finance.yahoo.com/v8/finance/chart/%5EVIX?range=5d&interval=1d", timeout=8
        )
        response.raise_for_status()
        valid = _yahoo_valid_rows(response.json())
        if len(valid) < 2:
            raise RuntimeError("yahoo close<2")
        trade_date = datetime.fromtimestamp(valid[-1][0], US_TZ).date()
        return _vix_from_close_rows(out, trade_date.isoformat(), valid[-1][1], valid[-2][1], config)
    except Exception as exc:
        out["error"] = str(exc)
        return out


def _empty_quote(source: str) -> dict:
    return {"ok": False, "source": source, "date": None, "close": None, "pct_chg": None, "error": None}


def _fetch_a50_with_akshare(out: dict) -> dict:
    import akshare as ak

    last_error = None
    for _ in range(3):
        try:
            return _a50_from_history(ak.futures_global_hist_em(symbol="CN00Y"), out)
        except Exception as exc:  # noqa: PERF203
            last_error = exc
            time.sleep(0.4)
    try:
        return _a50_from_spot(ak.futures_global_spot_em(), out)
    except Exception as spot_exc:
        raise RuntimeError(f"{last_error or 'hist_fail'}; spot_fallback={spot_exc}") from spot_exc


def _a50_from_history(df, out: dict) -> dict:
    if df is None or df.empty:
        raise RuntimeError("A50 empty")
    last = df.iloc[-1]
    out.update(
        {
            "ok": True,
            "date": str(last.get("日期")),
            "close": finite_float(last.get("最新价")),
            "pct_chg": finite_float(last.get("涨幅")),
        }
    )
    return out


def _a50_from_spot(spot, out: dict) -> dict:
    if spot is None or spot.empty:
        raise RuntimeError("A50 spot empty")
    hit = spot[spot["代码"].astype(str).str.upper() == "CN00Y"]
    if hit.empty:
        raise RuntimeError("A50 CN00Y not found in spot")
    row = hit.iloc[0]
    out.update(
        {
            "ok": True,
            "source": "akshare:futures_global_spot_em(CN00Y)",
            "date": datetime.now(TZ).strftime("%Y-%m-%d"),
            "close": finite_float(row.get("最新价") or row.get("昨结")),
            "pct_chg": finite_float(row.get("涨跌幅")),
        }
    )
    return out


def _parse_trade_date(raw: object) -> date | None:
    text = str(raw or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except Exception:
            continue
    return None


def _vix_from_close_rows(
    out: dict, raw_date: object, close_raw: object, previous_raw: object, config: PremarketRiskConfig
) -> dict:
    close = finite_float(close_raw)
    previous = finite_float(previous_raw)
    if close is None or previous is None or previous == 0:
        raise RuntimeError(f"{out['source']} close invalid")
    trade_date = ensure_vix_fresh(raw_date, out["source"], config)
    out.update(
        {"ok": True, "date": trade_date.isoformat(), "close": close, "pct_chg": (close - previous) / previous * 100.0}
    )
    return out


def _cboe_valid_rows(rows: list[dict]) -> list[tuple[str, float]]:
    valid: list[tuple[str, float]] = []
    for row in reversed(rows):
        close = finite_float(row.get("CLOSE"))
        raw_date = str(row.get("DATE", "")).strip()
        if close is not None and raw_date:
            valid.append((raw_date, close))
        if len(valid) >= 2:
            break
    return valid


def _yahoo_valid_rows(payload: dict) -> list[tuple[int, float]]:
    result = payload.get("chart", {}).get("result", [{}])[0]
    timestamps = result.get("timestamp") or []
    closes = result.get("indicators", {}).get("quote", [{}])[0].get("close", [])
    return [(int(ts), value) for ts, close in zip(timestamps, closes) if (value := finite_float(close)) is not None]


def _log_vix_retry(logger: Callable[[str], None], attempt: int, config: PremarketRiskConfig, vix: dict) -> None:
    logger(
        "VIX暂不可用，继续轮询: "
        f"attempt={attempt}/{config.vix_max_attempts}, "
        f"retry_in={config.vix_poll_interval_seconds}s, error={vix.get('error')}"
    )


def _vix_timeout_fallback(config: PremarketRiskConfig) -> dict:
    return {
        "ok": False,
        "source": "timeout_fallback",
        "date": None,
        "close": None,
        "pct_chg": None,
        "error": f"exceeded max attempts ({config.vix_max_attempts})",
    }


def _escalate_regime(current: str, target: str) -> str:
    severity_rank = {"NORMAL": 0, "CAUTION": 1, "RISK_OFF": 2, "BLACK_SWAN": 3}
    return target if severity_rank.get(target, 0) > severity_rank.get(current, 0) else current


def _judge_crash_or_caution(
    regime: str,
    reasons: list[str],
    a50_pct: float | None,
    vix_close: float | None,
    vix_pct: float | None,
    config: PremarketRiskConfig,
) -> str:
    if a50_pct is not None and a50_pct <= config.a50_crash_pct:
        regime = _escalate_regime(regime, "BLACK_SWAN")
        reasons.append(f"A50跌幅 {a50_pct:.2f}% <= {config.a50_crash_pct:.2f}%")
    if vix_pct is not None and vix_pct >= config.vix_crash_pct:
        regime = _judge_vix_crash_case(regime, reasons, vix_close, vix_pct, config)
    return regime


def _judge_vix_crash_case(
    regime: str,
    reasons: list[str],
    vix_close: float | None,
    vix_pct: float,
    config: PremarketRiskConfig,
) -> str:
    if vix_close is not None and vix_close >= config.vix_crash_close:
        reasons.append(
            f"VIX绝对值 {vix_close:.2f} >= {config.vix_crash_close:.2f} 且涨幅 {vix_pct:.2f}% >= {config.vix_crash_pct:.2f}%"
        )
        return _escalate_regime(regime, "BLACK_SWAN")
    if vix_close is None:
        reasons.append(f"VIX涨幅 {vix_pct:.2f}% >= {config.vix_crash_pct:.2f}%（绝对值缺失，按 CAUTION 处理）")
    else:
        reasons.append(
            f"VIX涨幅 {vix_pct:.2f}% >= {config.vix_crash_pct:.2f}% 但绝对值 {vix_close:.2f} < {config.vix_crash_close:.2f}，按 CAUTION 处理"
        )
    return _escalate_regime(regime, "CAUTION")


def _judge_risk_off(
    regime: str,
    reasons: list[str],
    a50_pct: float | None,
    vix_close: float | None,
    vix_pct: float | None,
    config: PremarketRiskConfig,
) -> str:
    if a50_pct is not None and a50_pct <= config.a50_risk_off_pct:
        regime = _escalate_regime(regime, "RISK_OFF")
        reasons.append(f"A50跌幅 {a50_pct:.2f}% <= {config.a50_risk_off_pct:.2f}%")
    if vix_pct is not None and vix_pct >= config.vix_risk_off_pct:
        is_caution = vix_pct >= config.vix_crash_pct and (vix_close is None or vix_close < config.vix_crash_close)
        if not is_caution:
            regime = _escalate_regime(regime, "RISK_OFF")
            reasons.append(f"VIX涨幅 {vix_pct:.2f}% >= {config.vix_risk_off_pct:.2f}%")
    return regime
