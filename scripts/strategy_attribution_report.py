from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from core.constants import TABLE_STRATEGY_ATTRIBUTION_REPORTS
from integrations.supabase_base import (
    close_client,
    create_admin_client,
    create_read_client,
    require_server_write_context,
)


def _num(raw: Any) -> float | None:
    try:
        if raw is None or str(raw).strip() == "":
            return None
        return float(raw)
    except (TypeError, ValueError):
        return None


def _json_map(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _str_list(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        text = str(item or "").strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def _candidate_shadow_fields(obs: dict[str, Any]) -> dict[str, Any]:
    features = _json_map(obs.get("features_json"))
    shadow_score = _json_map(features.get("candidate_shadow_score"))
    return {
        "candidate_shadow_score": _num(shadow_score.get("score")),
        "candidate_shadow_grade": str(shadow_score.get("grade") or "unknown").strip() or "unknown",
        "candidate_shadow_positive_tags": shadow_score.get("positive_tags") or [],
        "candidate_shadow_negative_tags": shadow_score.get("negative_tags") or [],
    }


def _data_lineage_fields(obs: dict[str, Any]) -> dict[str, Any]:
    features = _json_map(obs.get("features_json"))
    lineage = _json_map(features.get("data_lineage"))
    coverage_grade = str(lineage.get("coverage_grade") or "unknown").strip() or "unknown"
    return {
        "data_lineage_coverage_score": _num(lineage.get("coverage_score")),
        "data_lineage_coverage_grade": coverage_grade,
        "data_lineage_evidence_keys": _str_list(lineage.get("evidence_keys")),
        "data_lineage_missing_keys": _str_list(lineage.get("missing_keys")),
    }


def _fetch_all(client: Any, table: str, select: str, *, market: str, start: date, end: date) -> list[dict[str, Any]]:
    date_col = "trade_date" if table != "strategy_attribution_reports" else "report_date"
    rows: list[dict[str, Any]] = []
    offset = 0
    while True:
        query = (
            client.table(table)
            .select(select)
            .eq("market", market)
            .gte(date_col, start.isoformat())
            .lte(date_col, end.isoformat())
            .range(offset, offset + 999)
        )
        batch = query.execute().data or []
        rows.extend(batch)
        if len(batch) < 1000:
            return rows
        offset += 1000


def _stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    vals = [_num(r.get("return_pct")) for r in rows]
    vals = [v for v in vals if v is not None]
    dds = [_num(r.get("max_drawdown_pct")) for r in rows]
    dds = [v for v in dds if v is not None]
    if not vals:
        return {"count": 0}
    return {
        "count": len(vals),
        "avg_return_pct": round(sum(vals) / len(vals), 2),
        "median_return_pct": round(statistics.median(vals), 2),
        "win_rate_pct": round(sum(v > 0 for v in vals) / len(vals) * 100, 1),
        "big_win_rate_pct": round(sum(v >= 5 for v in vals) / len(vals) * 100, 1),
        "big_loss_rate_pct": round(sum(v <= -5 for v in vals) / len(vals) * 100, 1),
        "avg_drawdown_pct": round(sum(dds) / len(dds), 2) if dds else None,
        "best_return_pct": round(max(vals), 2),
        "worst_return_pct": round(min(vals), 2),
    }


def _join_outcomes(outcomes: list[dict[str, Any]], observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    obs_by_id = {row.get("id"): row for row in observations}
    joined = []
    for row in outcomes:
        obs = obs_by_id.get(row.get("observation_id"), {})
        item = dict(row)
        for key in (
            "name",
            "industry",
            "source",
            "channel",
            "selected_for_ai",
            "ai_recommended",
            "priority_score",
            "trigger_score",
            "stage",
            "springboard_grade",
            "springboard_met_count",
        ):
            item[key] = obs.get(key)
        item.update(_candidate_shadow_fields(obs))
        item.update(_data_lineage_fields(obs))
        joined.append(item)
    return joined


def _group_stats(rows: list[dict[str, Any]], group_key: str, horizons: list[int]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for horizon in horizons:
        horizon_rows = [r for r in rows if int(r.get("horizon_days") or 0) == horizon]
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in horizon_rows:
            groups[str(row.get(group_key) or "unknown")].append(row)
        result[str(horizon)] = {key: _stats(group_rows) for key, group_rows in sorted(groups.items())}
    return result


def _score_bucket_stats(rows: list[dict[str, Any]], horizons: list[int]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for horizon in horizons:
        horizon_rows = [
            r for r in rows if int(r.get("horizon_days") or 0) == horizon and _num(r.get("priority_score")) is not None
        ]
        scores = sorted(_num(r.get("priority_score")) for r in horizon_rows)
        if not scores:
            result[str(horizon)] = {}
            continue
        low_cut = scores[len(scores) // 3]
        high_cut = scores[len(scores) * 2 // 3]
        result[str(horizon)] = {
            "low": _stats([r for r in horizon_rows if (_num(r.get("priority_score")) or 0) <= low_cut]),
            "mid": _stats([r for r in horizon_rows if low_cut < (_num(r.get("priority_score")) or 0) <= high_cut]),
            "high": _stats([r for r in horizon_rows if (_num(r.get("priority_score")) or 0) > high_cut]),
        }
    return result


def _candidate_shadow_stats(rows: list[dict[str, Any]], horizons: list[int]) -> dict[str, Any]:
    result = _group_stats(rows, "candidate_shadow_grade", horizons)
    grade_order = {"S": 0, "A": 1, "B": 2, "C": 3, "D": 4, "unknown": 5}
    for horizon, stats_by_grade in list(result.items()):
        result[horizon] = {
            grade: stats
            for grade, stats in sorted(
                stats_by_grade.items(),
                key=lambda item: grade_order.get(item[0], 99),
            )
        }
    return result


def _coverage_grade_stats(rows: list[dict[str, Any]], horizons: list[int]) -> dict[str, Any]:
    result = _group_stats(rows, "data_lineage_coverage_grade", horizons)
    grade_order = {"strong": 0, "medium": 1, "thin": 2, "weak": 3, "unknown": 4}
    for horizon, stats_by_grade in list(result.items()):
        result[horizon] = {
            grade: stats
            for grade, stats in sorted(
                stats_by_grade.items(),
                key=lambda item: grade_order.get(item[0], 99),
            )
        }
    return result


def _evidence_key_stats(rows: list[dict[str, Any]], horizons: list[int]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for horizon in horizons:
        horizon_rows = [r for r in rows if int(r.get("horizon_days") or 0) == horizon]
        keys = sorted({key for row in horizon_rows for key in row.get("data_lineage_evidence_keys") or []})
        result[str(horizon)] = {
            key: _stats([row for row in horizon_rows if key in (row.get("data_lineage_evidence_keys") or [])])
            for key in keys
        }
    return result


def _coverage_summary(rows: list[dict[str, Any]], horizons: list[int]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for horizon in horizons:
        horizon_rows = [r for r in rows if int(r.get("horizon_days") or 0) == horizon]
        scores = [_num(r.get("data_lineage_coverage_score")) for r in horizon_rows]
        scores = [s for s in scores if s is not None]
        if not scores:
            result[str(horizon)] = {"count": 0}
            continue
        result[str(horizon)] = {
            "count": len(scores),
            "avg_coverage_score": round(sum(scores) / len(scores), 1),
            "strong_rate_pct": round(
                sum(str(r.get("data_lineage_coverage_grade")) == "strong" for r in horizon_rows)
                / len(horizon_rows)
                * 100,
                1,
            )
            if horizon_rows
            else 0.0,
        }
    return result


def _data_lineage_stats(rows: list[dict[str, Any]], horizons: list[int]) -> dict[str, Any]:
    return {
        "coverage_summary": _coverage_summary(rows, horizons),
        "coverage_grade": _coverage_grade_stats(rows, horizons),
        "evidence_key": _evidence_key_stats(rows, horizons),
    }


def _score_stats_json(joined: list[dict[str, Any]], horizons: list[int]) -> dict[str, Any]:
    stats = _score_bucket_stats(joined, horizons)
    stats["_candidate_shadow_grade"] = _candidate_shadow_stats(joined, horizons)
    stats["_data_lineage"] = _data_lineage_stats(joined, horizons)
    return stats


def _ranked(rows: list[dict[str, Any]], horizon: int, *, reverse: bool) -> list[dict[str, Any]]:
    picked = [r for r in rows if int(r.get("horizon_days") or 0) == horizon and _num(r.get("return_pct")) is not None]
    ranked = sorted(picked, key=lambda r: _num(r.get("return_pct")) or 0, reverse=reverse)
    keys = [
        "trade_date",
        "code",
        "name",
        "signal_type",
        "track",
        "regime",
        "return_pct",
        "max_drawdown_pct",
        "priority_score",
        "candidate_shadow_score",
        "candidate_shadow_grade",
        "data_lineage_coverage_score",
        "data_lineage_coverage_grade",
        "data_lineage_evidence_keys",
    ]
    return [{key: row.get(key) for key in keys} for row in ranked[:20]]


def _outcome_by_code_date(
    rows: list[dict[str, Any]], horizons: list[int]
) -> dict[tuple[str, str, int], dict[str, Any]]:
    outcome_map: dict[tuple[str, str, int], dict[str, Any]] = {}
    valid_horizons = {int(h) for h in horizons}
    for row in rows:
        horizon = int(row.get("horizon_days") or 0)
        if horizon not in valid_horizons or _num(row.get("return_pct")) is None:
            continue
        key = (str(row.get("trade_date") or "")[:10], str(row.get("code") or "").strip(), horizon)
        outcome_map.setdefault(key, row)
    return outcome_map


def _shadow_side_stats(
    shadow_rows: list[dict[str, Any]],
    outcome_map: dict[tuple[str, str, int], dict[str, Any]],
    *,
    side: str,
    horizon: int,
) -> dict[str, Any]:
    matched: list[dict[str, Any]] = []
    total = 0
    for row in shadow_rows:
        trade_date = str(row.get("trade_date") or "")[:10]
        for code in row.get(side) or []:
            total += 1
            outcome = outcome_map.get((trade_date, str(code).strip(), horizon))
            if outcome:
                matched.append(outcome)
    stats = _stats(matched)
    stats.update(
        {
            "shadow_candidates": total,
            "matched_outcomes": stats.get("count", 0),
            "missing_outcomes": max(total - int(stats.get("count", 0)), 0),
        }
    )
    return stats


def _shadow_outcome_stats(
    shadow_rows: list[dict[str, Any]],
    outcome_rows: list[dict[str, Any]],
    horizons: list[int],
) -> dict[str, Any]:
    outcome_map = _outcome_by_code_date(outcome_rows, horizons)
    return {
        str(horizon): {
            "added": _shadow_side_stats(shadow_rows, outcome_map, side="diff_added", horizon=horizon),
            "removed": _shadow_side_stats(shadow_rows, outcome_map, side="diff_removed", horizon=horizon),
        }
        for horizon in horizons
    }


def _shadow_stats(
    shadow_rows: list[dict[str, Any]], outcome_rows: list[dict[str, Any]], horizons: list[int]
) -> dict[str, Any]:
    if not shadow_rows:
        return {"count": 0, "outcome_stats": {}}
    added = sum(len(r.get("diff_added") or []) for r in shadow_rows)
    removed = sum(len(r.get("diff_removed") or []) for r in shadow_rows)
    return {
        "count": len(shadow_rows),
        "avg_added": round(added / len(shadow_rows), 2),
        "avg_removed": round(removed / len(shadow_rows), 2),
        "latest": shadow_rows[-1],
        "outcome_stats": _shadow_outcome_stats(shadow_rows, outcome_rows, horizons),
    }


def build_report(client: Any, market: str, days: int, horizons: list[int]) -> dict[str, Any]:
    end = date.today()
    start = end - timedelta(days=days)
    observations = _fetch_all(client, "signal_observations", "*", market=market, start=start, end=end)
    outcomes = _fetch_all(client, "signal_outcomes", "*", market=market, start=start, end=end)
    shadow = _fetch_all(client, "signal_policy_shadow_runs", "*", market=market, start=start, end=end)
    joined = _join_outcomes(outcomes, observations)
    focus_horizon = 3 if 3 in horizons else horizons[0]
    return {
        "report_date": end.isoformat(),
        "market": market,
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "horizons": horizons,
        "summary_json": _group_stats(joined, "horizon_days", horizons),
        "signal_stats_json": _group_stats(joined, "signal_type", horizons),
        "score_bucket_stats_json": _score_stats_json(joined, horizons),
        "shadow_diff_stats_json": _shadow_stats(shadow, joined, horizons),
        "top_winners_json": _ranked(joined, focus_horizon, reverse=True),
        "top_losers_json": _ranked(joined, focus_horizon, reverse=False),
        "recommendations_json": _recommendations(joined, horizons),
    }


def _recommendations(rows: list[dict[str, Any]], horizons: list[int]) -> list[dict[str, str]]:
    signal_stats = _group_stats(rows, "signal_type", horizons)
    recs = []
    for horizon, stats_by_signal in signal_stats.items():
        for signal, stats in stats_by_signal.items():
            if stats.get("count", 0) < 10:
                continue
            if stats.get("avg_return_pct", 0) < -3 or stats.get("big_loss_rate_pct", 0) >= 50:
                recs.append(
                    {
                        "type": "downweight",
                        "horizon": horizon,
                        "target": signal,
                        "reason": json.dumps(stats, ensure_ascii=False),
                    }
                )
    return recs


def _write_artifacts(report: dict[str, Any], output_dir: str) -> None:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    shadow = report.get("shadow_diff_stats_json") or {}
    shadow_h5 = ((shadow.get("outcome_stats") or {}).get("5") or {}) if isinstance(shadow, dict) else {}
    lines = [
        f"# 策略归因报告 {report['report_date']}",
        "",
        f"- 市场: `{report['market']}`",
        f"- 窗口: `{report['window_start']}` 至 `{report['window_end']}`",
        "",
        "## Shadow 差异",
        f"- run 数: `{shadow.get('count', 0) if isinstance(shadow, dict) else 0}`",
        f"- 平均新增: `{shadow.get('avg_added', 0) if isinstance(shadow, dict) else 0}`",
        f"- 平均移除: `{shadow.get('avg_removed', 0) if isinstance(shadow, dict) else 0}`",
        f"- h=5 新增组: `{json.dumps(shadow_h5.get('added') or {}, ensure_ascii=False)}`",
        f"- h=5 移除组: `{json.dumps(shadow_h5.get('removed') or {}, ensure_ascii=False)}`",
    ]
    lines += [
        "",
        "## 降权建议",
        *[f"- `{r['target']}` h={r['horizon']}: {r['reason']}" for r in report["recommendations_json"]],
    ]
    (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _create_user_read_client() -> Any | None:
    try:
        from cli.auth import restore_session
        from integrations.supabase_base import create_user_client

        session = restore_session()
        if session and session.get("access_token"):
            return create_user_client(session["access_token"], session.get("refresh_token", ""))
    except Exception:
        return None
    return None


def _create_report_client(*, no_write: bool) -> Any:
    if no_write:
        return _create_user_read_client() or create_read_client()
    require_server_write_context("write strategy_attribution_reports")
    return create_admin_client()


def main() -> None:
    parser = argparse.ArgumentParser(description="Build strategy attribution report")
    parser.add_argument("--market", default="cn")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--horizons", default="1,3,5,10,20")
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()
    horizons = [int(x) for x in args.horizons.split(",") if x.strip()]
    client = _create_report_client(no_write=args.no_write)
    try:
        report = build_report(client, args.market, args.days, horizons)
        report["created_at"] = datetime.now(UTC).isoformat()
        if not args.no_write:
            client.table(TABLE_STRATEGY_ATTRIBUTION_REPORTS).upsert(
                report,
                on_conflict="report_date,market,window_start,window_end",
            ).execute()
        if args.output_dir:
            _write_artifacts(report, args.output_dir)
        print(
            json.dumps(
                {"market": args.market, "report_date": report["report_date"], "written": not args.no_write},
                ensure_ascii=False,
            )
        )
    finally:
        close_client(client)


if __name__ == "__main__":
    main()
