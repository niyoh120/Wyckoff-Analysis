"""Backfill recommendation_tracking rows from curated historical report presets."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo

import pandas as pd

if __name__ == "__main__" or not __package__:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from integrations.supabase_recommendation import (
    prepare_recommendation_payload,
    upsert_recommendation_payload,
    write_recommendation_backup_artifact,
)
from integrations.tickflow_client import TickFlowClient, normalize_cn_symbol

CN_TZ = ZoneInfo("Asia/Shanghai")
PRESETS = {
    "20260526-l4": {
        "recommend_date": 20260526,
        "ai_codes": {"600203", "300679"},
        "rows": [
            ("605389", "长龄液压", 0.93, "多信号共振/LPS+TrendPB"),
            ("301269", "华大九天", 9.05, "SOS（强势信号）"),
            ("301591", "肯特股份", 6.46, "SOS（强势信号）"),
            ("002184", "海得控制", 6.16, "SOS（强势信号）"),
            ("605580", "恒盛能源", 6.15, "SOS（强势信号）"),
            ("300718", "长盛轴承", 5.94, "SOS（强势信号）"),
            ("600203", "福日电子", 5.73, "SOS（强势信号）"),
            ("300809", "华辰装备", 5.73, "SOS（强势信号）"),
            ("003028", "振邦智能", 4.68, "SOS（强势信号）"),
            ("002896", "中大力德", 4.33, "SOS（强势信号）"),
            ("300560", "中富通", 4.14, "SOS（强势信号）"),
            ("300779", "惠城环保", 4.07, "SOS（强势信号）"),
            ("300100", "双林股份", 3.19, "SOS（强势信号）"),
            ("003019", "宸展光电", 2.88, "SOS（强势信号）"),
            ("300550", "和仁科技", 2.80, "SOS（强势信号）"),
            ("000670", "盈方微", 2.75, "SOS（强势信号）"),
            ("600378", "昊华科技", 2.71, "SOS（强势信号）"),
            ("002036", "联创电子", 4.07, "EVR（放量不跌）"),
            ("000536", "华映科技", 2.97, "EVR（放量不跌）"),
            ("300566", "激智科技", 2.96, "EVR（放量不跌）"),
            ("002747", "埃斯顿", 2.23, "EVR（放量不跌）"),
            ("301026", "浩通科技", 1.73, "EVR（放量不跌）"),
            ("603373", "安邦护卫", 1.70, "EVR（放量不跌）"),
            ("300952", "恒辉安防", 1.68, "EVR（放量不跌）"),
            ("600909", "华安证券", 1.58, "EVR（放量不跌）"),
            ("301099", "雅创电子", 0.48, "LPS（最后支撑点）"),
            ("300400", "劲拓股份", 0.47, "LPS（最后支撑点）"),
            ("300868", "杰美特", 0.44, "LPS（最后支撑点）"),
            ("002346", "柘中股份", 0.41, "LPS（最后支撑点）"),
            ("600791", "京能置业", 0.39, "LPS（最后支撑点）"),
            ("300936", "中英科技", 0.38, "LPS（最后支撑点）"),
            ("300679", "电连技术", 0.37, "LPS（最后支撑点）"),
            ("301189", "奥尼电子", 0.35, "LPS（最后支撑点）"),
            ("603045", "福达合金", 0.53, "TrendPB 趋势回踩"),
            ("601609", "金田股份", 0.35, "TrendPB 趋势回踩"),
        ],
    }
}


def _day_bounds_ms(recommend_date: int) -> tuple[int, int]:
    day = datetime.strptime(str(recommend_date), "%Y%m%d").date()
    start = datetime.combine(day, time.min, tzinfo=CN_TZ)
    end = datetime.combine(day, time.max, tzinfo=CN_TZ)
    return int(start.timestamp() * 1000), int(end.timestamp() * 1000)


def _close_price(df: pd.DataFrame | None, recommend_date: int) -> float:
    if df is None or df.empty or not {"date", "close"}.issubset(df.columns):
        return 0.0
    day = datetime.strptime(str(recommend_date), "%Y%m%d").date().isoformat()
    work = df[df["date"].astype(str) == day].copy()
    if work.empty:
        return 0.0
    close = pd.to_numeric(work["close"], errors="coerce").dropna()
    return float(close.iloc[-1]) if not close.empty and float(close.iloc[-1]) > 0 else 0.0


def _fetch_close_map(codes: list[str], recommend_date: int) -> dict[str, float]:
    api_key = os.getenv("TICKFLOW_API_KEY", "").strip()
    start_ms, end_ms = _day_bounds_ms(recommend_date)
    client = TickFlowClient(api_key=api_key)
    symbols = [normalize_cn_symbol(code) for code in codes]
    hist_map = client.get_klines_batch(
        symbols,
        period="1d",
        count=10,
        start_time_ms=start_ms,
        end_time_ms=end_ms,
        adjust="forward",
    )
    return {code: _close_price(hist_map.get(normalize_cn_symbol(code)), recommend_date) for code in codes}


def _symbols_info(preset: dict, close_map: dict[str, float]) -> list[dict]:
    out = []
    for code, name, score, tag in preset["rows"]:
        price = close_map.get(code, 0.0)
        if price <= 0:
            raise RuntimeError(f"missing TickFlow close for {code} {name}")
        out.append({"code": code, "name": name, "funnel_score": score, "tag": tag, "initial_price": price})
    return out


def _apply_ai_flags(payload: list[dict], ai_codes: set[str]) -> None:
    for row in payload:
        code = f"{int(row.get('code')):06d}" if row.get("code") is not None else ""
        row["is_ai_recommended"] = code in ai_codes
        row["updated_at"] = datetime.now(UTC).isoformat()


def run_backfill(preset_name: str, artifacts_dir: str) -> int:
    preset = PRESETS[preset_name]
    recommend_date = int(preset["recommend_date"])
    codes = [row[0] for row in preset["rows"]]
    close_map = _fetch_close_map(codes, recommend_date)
    symbols_info = _symbols_info(preset, close_map)
    payload = prepare_recommendation_payload(recommend_date, symbols_info)
    _apply_ai_flags(payload, set(preset["ai_codes"]))
    if len(payload) != len(codes):
        raise RuntimeError(f"payload count mismatch: {len(payload)} != {len(codes)}")
    ok = upsert_recommendation_payload(payload)
    if not ok:
        raise RuntimeError("Supabase upsert failed")
    paths = write_recommendation_backup_artifact(
        recommend_date,
        payload,
        artifacts_dir,
        ai_codes=sorted(preset["ai_codes"]),
    )
    print(f"[backfill] preset={preset_name} recommend_date={recommend_date} rows={len(payload)} ok={ok}")
    print(f"[backfill] artifacts={', '.join(paths) if paths else '-'}")
    return len(payload)


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill recommendation_tracking from historical report presets.")
    parser.add_argument("--preset", default="20260526-l4", choices=sorted(PRESETS))
    parser.add_argument("--artifacts-dir", default=os.getenv("BACKFILL_ARTIFACTS_DIR", "artifacts"))
    args = parser.parse_args()
    run_backfill(args.preset, args.artifacts_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
