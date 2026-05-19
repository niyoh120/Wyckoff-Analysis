from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any

import requests


class StrategyApiError(RuntimeError):
    pass


@dataclass(frozen=True)
class StrategyApiConfig:
    base_url: str
    api_key: str
    mode: str
    timeout_seconds: float
    poll_interval_seconds: float
    poll_timeout_seconds: float
    strategy_version: str


def _env_float(name: str, default: float) -> float:
    raw = str(os.getenv(name, "") or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _clean_mode(raw: str) -> str:
    mode = str(raw or "remote").strip().lower()
    if mode in {"api", "required"}:
        return "remote"
    if mode not in {"local", "auto", "remote"}:
        return "remote"
    return mode


def get_strategy_api_config() -> StrategyApiConfig:
    return StrategyApiConfig(
        base_url=str(os.getenv("WYCKOFF_STRATEGY_API_URL", "") or "").strip().rstrip("/"),
        api_key=str(os.getenv("WYCKOFF_STRATEGY_API_KEY", "") or "").strip(),
        mode=_clean_mode(str(os.getenv("WYCKOFF_STRATEGY_API_MODE", "remote") or "remote")),
        timeout_seconds=_env_float("WYCKOFF_STRATEGY_API_TIMEOUT", 180.0),
        poll_interval_seconds=_env_float("WYCKOFF_STRATEGY_API_POLL_INTERVAL", 2.0),
        poll_timeout_seconds=_env_float("WYCKOFF_STRATEGY_API_POLL_TIMEOUT", 600.0),
        strategy_version=str(os.getenv("WYCKOFF_STRATEGY_VERSION", "private-v1") or "private-v1").strip(),
    )


def is_strategy_api_configured(config: StrategyApiConfig | None = None) -> bool:
    cfg = config or get_strategy_api_config()
    return bool(cfg.base_url and cfg.api_key)


def is_strategy_api_required(config: StrategyApiConfig | None = None) -> bool:
    cfg = config or get_strategy_api_config()
    return cfg.mode == "remote"


def is_strategy_api_enabled(config: StrategyApiConfig | None = None) -> bool:
    cfg = config or get_strategy_api_config()
    return cfg.mode == "remote" or (cfg.mode == "auto" and is_strategy_api_configured(cfg))


def _require_config(config: StrategyApiConfig | None = None) -> StrategyApiConfig:
    cfg = config or get_strategy_api_config()
    if not cfg.base_url:
        raise StrategyApiError("WYCKOFF_STRATEGY_API_URL is not configured")
    if not cfg.api_key:
        raise StrategyApiError("WYCKOFF_STRATEGY_API_KEY is not configured")
    return cfg


def _request(method: str, path: str, *, json_payload: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = _require_config()
    url = f"{cfg.base_url}{path}"
    try:
        response = requests.request(
            method,
            url,
            headers={"X-API-Key": cfg.api_key, "Accept": "application/json"},
            json=json_payload,
            timeout=cfg.timeout_seconds,
        )
    except requests.RequestException as exc:
        raise StrategyApiError(f"Strategy API request failed: {exc}") from exc

    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if response.status_code >= 400:
        detail = payload.get("detail") if isinstance(payload, dict) else None
        raise StrategyApiError(f"Strategy API {response.status_code}: {detail or response.text[:200]}")
    if not isinstance(payload, dict):
        raise StrategyApiError("Strategy API returned a non-object response")
    return payload


def _clean_code(code: str) -> str:
    text = str(code or "").strip().upper()
    if text.isdigit() and len(text) <= 6:
        return text.zfill(6)
    return text


def _json_float(value: Any) -> float | None:
    if value in {None, ""}:
        return None
    try:
        return round(float(value), 4)
    except (TypeError, ValueError):
        return None


def _health_from_rating(rating: str, risk_level: str) -> str:
    if rating in {"strong", "candidate"} and risk_level != "high":
        return "healthy"
    if rating == "watch" or risk_level == "medium":
        return "watch"
    return "avoid"


def _pnl_pct(latest_close: Any, cost: float) -> float | None:
    close = _json_float(latest_close)
    if close is None or cost <= 0:
        return None
    return round((close / float(cost) - 1.0) * 100.0, 2)


def _normalize_screen_board(board: str) -> str:
    board_norm = str(board or "all").strip().lower()
    board_norm = {
        "gem": "chinext",
        "创业板": "chinext",
        "主板": "main",
        "全部": "all",
        "main_chinext": "all",
        "main-chinext": "all",
        "main+chinext": "all",
    }.get(board_norm, board_norm)
    if board_norm not in {"all", "main", "chinext"}:
        raise StrategyApiError(f"Unsupported strategy API board: {board}")
    return board_norm


def _screen_payload(
    *,
    board: str,
    universe: list[str] | None,
    top_n: int,
    trade_date: str | None,
    strategy_version: str,
    include_signal_confirmation: bool,
    include_springboard_scoring: bool,
) -> dict[str, Any]:
    return {
        "trade_date": trade_date,
        "universe": [_clean_code(code) for code in universe] if universe else None,
        "board": _normalize_screen_board(board),
        "top_n": max(1, min(int(top_n or 20), 200)),
        "include_signal_confirmation": bool(include_signal_confirmation),
        "include_springboard_scoring": bool(include_springboard_scoring),
        "strategy_version": strategy_version,
    }


def _screen_candidate_rows(candidates: list[Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    symbols_for_report: list[dict[str, Any]] = []
    trigger_rows: list[dict[str, Any]] = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        score = _json_float(item.get("score")) or 0.0
        reasons = item.get("reasons") or []
        tag = str(item.get("tag") or item.get("recommend_reason") or "").strip()
        if not tag and isinstance(reasons, list) and reasons:
            tag = str(reasons[0] or "").strip()
        row = {
            "code": str(item.get("code") or ""),
            "name": str(item.get("name") or item.get("code") or ""),
            "score": score,
            "priority_score": score,
            "track": str(item.get("phase") or ""),
            "tag": tag or "strategy_api",
            "risk_level": str(item.get("risk_level") or ""),
            "reasons": reasons,
        }
        symbols_for_report.append(row)
        trigger_rows.append({"code": row["code"], "name": row["name"], "score": row["score"]})
    return symbols_for_report, trigger_rows


def _screen_report_rows(rows: list[Any]) -> list[dict[str, Any]]:
    symbols_for_report: list[dict[str, Any]] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        row = dict(item)
        code = str(row.get("code") or "").strip()
        if not code:
            continue
        row["code"] = code
        row["name"] = str(row.get("name") or code)
        priority_score = _json_float(row.get("priority_score"))
        score = _json_float(row.get("score"))
        if priority_score is None and score is not None:
            row["priority_score"] = score
        if score is None and priority_score is not None:
            row["score"] = priority_score
        tag = str(row.get("tag") or row.get("recommend_reason") or "").strip()
        if not tag:
            reasons = row.get("reasons") or []
            if isinstance(reasons, list) and reasons:
                tag = str(reasons[0] or "").strip()
        row["tag"] = tag or "strategy_api"
        symbols_for_report.append(row)
    return symbols_for_report


def _screen_legacy_result(data: dict[str, Any]) -> dict[str, Any]:
    candidates = data.get("candidates") or []
    if not isinstance(candidates, list):
        candidates = []
    candidate_symbols, trigger_rows = _screen_candidate_rows(candidates)
    raw_symbols = data.get("symbols_for_report") or []
    symbols_for_report = _screen_report_rows(raw_symbols) if isinstance(raw_symbols, list) else []
    if not symbols_for_report:
        symbols_for_report = candidate_symbols
    total_scanned = int(data.get("total_scanned") or len(symbols_for_report))
    summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
    trigger_groups = data.get("trigger_groups") if isinstance(data.get("trigger_groups"), dict) else {}
    has_selected_for_ai = "selected_for_ai" in data
    selected_for_ai = data.get("selected_for_ai") if isinstance(data.get("selected_for_ai"), list) else []
    if not has_selected_for_ai and not selected_for_ai:
        selected_for_ai = [row.get("code") for row in symbols_for_report]
    if "selected_for_ai" in summary:
        selected_count = int(summary.get("selected_for_ai") or 0)
    else:
        selected_count = len(selected_for_ai)
    return {
        "ok": True,
        "source": "strategy_api",
        "strategy_version": data.get("strategy_version"),
        "trade_date": data.get("trade_date"),
        "summary": {
            "total_scanned": total_scanned,
            "layer1_passed": int(summary.get("layer1_passed") or total_scanned),
            "layer2_passed": int(summary.get("layer2_passed") or len(symbols_for_report)),
            "layer3_passed": int(summary.get("layer3_passed") or len(symbols_for_report)),
            "l4_unique_hits": int(summary.get("l4_unique_hits") or len(symbols_for_report)),
            "selected_for_ai": selected_count,
        },
        "trigger_groups": trigger_groups or {"strategy_api": trigger_rows},
        "top_sectors": data.get("top_sectors") if isinstance(data.get("top_sectors"), list) else [],
        "benchmark_context": data.get("benchmark_context") if isinstance(data.get("benchmark_context"), dict) else {},
        "symbols_for_report": symbols_for_report,
        "selected_for_ai": selected_for_ai,
        "trend_selected": data.get("trend_selected") if isinstance(data.get("trend_selected"), list) else [],
        "accum_selected": data.get("accum_selected") if isinstance(data.get("accum_selected"), list) else [],
        "signal_confirmation_count": int(data.get("signal_confirmation_count") or 0),
        "springboard_scored_count": int(data.get("springboard_scored_count") or 0),
        "candidates": candidates,
    }


def analyze_stock_legacy(
    code: str,
    *,
    name: str | None = None,
    cost: float = 0.0,
    trade_date: str | None = None,
    include_explanation: bool = True,
    user_id: str | None = None,
) -> dict[str, Any]:
    cfg = _require_config()
    data = _request(
        "POST",
        "/v1/analyze",
        json_payload={
            "code": _clean_code(code),
            "name": name,
            "cost": cost,
            "trade_date": trade_date,
            "include_explanation": include_explanation,
            "strategy_version": cfg.strategy_version,
            "user_id": user_id,
        },
    )
    setups = [str(item) for item in data.get("setups") or [] if str(item or "").strip()]
    risk_notes = [str(item) for item in data.get("risk_notes") or [] if str(item or "").strip()]
    latest_close = data.get("latest_close")
    return {
        "source": "strategy_api",
        "code": str(data.get("code") or _clean_code(code)),
        "name": data.get("name") or name or _clean_code(code),
        "health": _health_from_rating(str(data.get("rating") or ""), str(data.get("risk_level") or "")),
        "pnl_pct": _pnl_pct(latest_close, float(cost or 0.0)),
        "latest_close": latest_close,
        "score": data.get("score"),
        "rating": data.get("rating"),
        "risk_level": data.get("risk_level"),
        "ma_pattern": data.get("phase"),
        "l2_channel": setups[0] if setups else data.get("phase"),
        "track": data.get("phase"),
        "accum_stage": data.get("phase"),
        "l4_triggers": setups[1:] if len(setups) > 1 else [],
        "health_reasons": risk_notes,
        "formatted_text": data.get("explanation") or "",
        "data_status": "ok",
        "latest_date": data.get("trade_date") or trade_date,
        "strategy_version": data.get("strategy_version"),
    }


def screen_stocks_legacy(
    *,
    board: str = "all",
    universe: list[str] | None = None,
    top_n: int = 20,
    trade_date: str | None = None,
    include_signal_confirmation: bool = False,
    include_springboard_scoring: bool = False,
) -> dict[str, Any]:
    cfg = _require_config()
    payload = _screen_payload(
        board=board,
        universe=universe,
        top_n=top_n,
        trade_date=trade_date,
        strategy_version=cfg.strategy_version,
        include_signal_confirmation=include_signal_confirmation,
        include_springboard_scoring=include_springboard_scoring,
    )
    try:
        accepted = _request("POST", "/v1/screen/jobs", json_payload=payload)
    except StrategyApiError as exc:
        # Keep compatibility while the API deployment rolls forward.
        if "Strategy API 404" not in str(exc):
            raise
        data = _request("POST", "/v1/screen", json_payload=payload)
        return _screen_legacy_result(data)

    task_id = str(accepted.get("task_id") or "").strip()
    if not task_id:
        raise StrategyApiError("Strategy API screen task did not return a task_id")
    task = wait_for_task(task_id)
    data = task.get("result") or {}
    if not isinstance(data, dict):
        raise StrategyApiError("Strategy API screen task result is not an object")
    return _screen_legacy_result(data)


def _backtest_payload(
    *,
    start: str,
    end: str,
    hold_days: int,
    top_n: int,
    board: str,
    stop_loss_pct: float,
    take_profit_pct: float | None,
    strategy_version: str,
    execution_strategy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "start_date": start,
        "end_date": end,
        "board": board,
        "top_n": top_n,
        "hold_days": [hold_days],
        "stop_loss": [stop_loss_pct],
        "take_profit": [take_profit_pct],
        "strategy_version": strategy_version,
    }
    if execution_strategy:
        payload["execution_strategy"] = execution_strategy
    return payload


def _backtest_legacy_result(
    *,
    start: str,
    end: str,
    board: str,
    hold_days: int,
    top_n: int,
    stop_loss_pct: float,
    take_profit_pct: float | None,
    execution_strategy: dict[str, Any] | None,
    task: dict[str, Any],
) -> dict[str, Any]:
    result = task.get("result") or {}
    if not isinstance(result, dict):
        raise StrategyApiError("Strategy API task result is not an object")
    best = result.get("best") or {}
    if not isinstance(best, dict):
        best = {}
    result_strategy = result.get("execution_strategy")
    if not isinstance(result_strategy, dict):
        result_strategy = execution_strategy or {}
    return {
        "source": "strategy_api",
        "period": f"{start} ~ {end}",
        "hold_days": best.get("hold_days", hold_days),
        "top_n": result.get("top_n", top_n),
        "board": board,
        "execution_strategy": result_strategy,
        "strategy_id": result_strategy.get("id"),
        "strategy_name": result_strategy.get("name"),
        "stop_loss_pct": best.get("stop_loss_pct", stop_loss_pct),
        "take_profit_pct": best.get("take_profit_pct", take_profit_pct),
        "trades": best.get("trades", 0),
        "win_rate_pct": best.get("win_rate_pct"),
        "avg_ret_pct": best.get("avg_ret_pct"),
        "median_ret_pct": best.get("median_ret_pct"),
        "sharpe_ratio": best.get("sharpe_ratio"),
        "max_drawdown_pct": best.get("max_drawdown_pct"),
        "portfolio_total_ret_pct": best.get("portfolio_total_ret_pct"),
        "portfolio_ann_ret_pct": best.get("portfolio_ann_ret_pct"),
        "rows": result.get("rows") or [],
        "task_id": task.get("task_id"),
        "strategy_version": result.get("strategy_version"),
    }


def wait_for_task(task_id: str) -> dict[str, Any]:
    cfg = _require_config()
    deadline = time.monotonic() + cfg.poll_timeout_seconds
    while True:
        task = _request("GET", f"/v1/tasks/{task_id}")
        status = str(task.get("status") or "")
        if status == "completed":
            return task
        if status == "failed":
            raise StrategyApiError(str(task.get("error") or "Strategy API task failed"))
        if time.monotonic() >= deadline:
            raise StrategyApiError(f"Strategy API task timed out: {task_id}")
        time.sleep(max(0.2, cfg.poll_interval_seconds))


def run_backtest_legacy(
    *,
    start: str,
    end: str,
    hold_days: int,
    top_n: int,
    board: str,
    stop_loss_pct: float,
    take_profit_pct: float | None,
    execution_strategy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = _require_config()
    accepted = _request(
        "POST",
        "/v1/backtest",
        json_payload=_backtest_payload(
            start=start,
            end=end,
            hold_days=hold_days,
            top_n=top_n,
            board=board,
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
            strategy_version=cfg.strategy_version,
            execution_strategy=execution_strategy,
        ),
    )
    task = wait_for_task(str(accepted.get("task_id") or ""))
    return _backtest_legacy_result(
        start=start,
        end=end,
        board=board,
        hold_days=hold_days,
        top_n=top_n,
        stop_loss_pct=stop_loss_pct,
        take_profit_pct=take_profit_pct,
        execution_strategy=execution_strategy,
        task=task,
    )


def score_tail_buy_remote(
    *,
    candidates: list[dict[str, Any]],
    intraday_by_code: dict[str, list[dict[str, Any]]],
    style: str = "auto",
) -> dict[str, Any]:
    cfg = _require_config()
    return _request(
        "POST",
        "/v1/tail-buy/score",
        json_payload={
            "strategy_version": cfg.strategy_version,
            "candidates": candidates,
            "intraday_by_code": intraday_by_code,
            "style": style,
        },
    )


def prepare_tail_buy_remote(
    *,
    candidates: list[dict[str, Any]],
    depth_by_code: dict[str, dict[str, Any]] | None = None,
    style: str = "auto",
    max_llm_symbols: int = 20,
    llm_min_rule_score: float = 60.0,
    llm_allowed_rule_decisions: list[str] | tuple[str, ...] = ("BUY", "WATCH"),
) -> dict[str, Any]:
    cfg = _require_config()
    return _request(
        "POST",
        "/v1/tail-buy/prepare",
        json_payload={
            "strategy_version": cfg.strategy_version,
            "candidates": candidates,
            "depth_by_code": depth_by_code or {},
            "style": style,
            "max_llm_symbols": max(int(max_llm_symbols), 0),
            "llm_min_rule_score": max(float(llm_min_rule_score), 0.0),
            "llm_allowed_rule_decisions": [
                str(x).strip().upper() for x in llm_allowed_rule_decisions if str(x).strip()
            ],
        },
    )


def finalize_tail_buy_remote(
    *,
    candidates: list[dict[str, Any]],
    llm_outputs: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    cfg = _require_config()
    return _request(
        "POST",
        "/v1/tail-buy/finalize",
        json_payload={
            "strategy_version": cfg.strategy_version,
            "candidates": candidates,
            "llm_outputs": llm_outputs,
        },
    )


def analyze_tail_buy_holdings_remote(
    *,
    holdings: list[dict[str, Any]],
    style: str = "auto",
    hard_stop_pct: float = 6.0,
) -> dict[str, Any]:
    cfg = _require_config()
    return _request(
        "POST",
        "/v1/tail-buy/holdings",
        json_payload={
            "strategy_version": cfg.strategy_version,
            "holdings": holdings,
            "style": style,
            "hard_stop_pct": hard_stop_pct,
        },
    )


def run_step4_rebalance_remote(
    *,
    external_report: str,
    benchmark_context: dict[str, Any] | None,
    llm_api_key: str,
    model: str,
    candidate_meta: list[dict[str, Any]] | None,
    portfolio_id: str,
    tg_bot_token: str,
    tg_chat_id: str,
    holdings_intraday_report: str = "",
) -> dict[str, Any]:
    cfg = _require_config()
    return _request(
        "POST",
        "/v1/step4/rebalance",
        json_payload={
            "strategy_version": cfg.strategy_version,
            "external_report": external_report,
            "benchmark_context": benchmark_context or {},
            "llm_api_key": llm_api_key,
            "model": model,
            "candidate_meta": candidate_meta or [],
            "portfolio_id": portfolio_id,
            "tg_bot_token": tg_bot_token,
            "tg_chat_id": tg_chat_id,
            "holdings_intraday_report": holdings_intraday_report,
        },
    )
