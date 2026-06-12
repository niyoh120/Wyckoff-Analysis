"""Build shadow strategy reflections from signal feedback tables."""

from __future__ import annotations

import argparse
import json
import os
import sys
from contextlib import suppress
from datetime import date

if __name__ == "__main__" or not __package__:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

with suppress(Exception):
    from dotenv import load_dotenv

    load_dotenv()

from core.strategy_reflection import build_policy_candidate, build_strategy_reflection
from integrations.supabase_signal_feedback import load_policy_shadow_runs, load_recent_signal_outcomes
from integrations.supabase_strategy_reflection import upsert_strategy_policy_candidate, upsert_strategy_reflection


def _enabled() -> bool:
    return os.getenv("WYCKOFF_STRATEGY_REFLECTION", "off").strip().lower() == "shadow"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refresh strategy reflection shadow artifacts.")
    parser.add_argument("--market", default="cn")
    parser.add_argument("--as-of-date", default=date.today().isoformat())
    parser.add_argument("--horizon-days", type=int, default=int(os.getenv("SIGNAL_REGISTRY_HORIZON", "5")))
    parser.add_argument("--outcome-days", type=int, default=180)
    parser.add_argument("--shadow-days", type=int, default=30)
    parser.add_argument("--limit", type=int, default=20000)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def _build_payloads(args: argparse.Namespace) -> tuple[dict, dict | None]:
    outcomes = load_recent_signal_outcomes(args.outcome_days, args.limit, args.market)
    shadow_runs = load_policy_shadow_runs(args.shadow_days, args.limit, args.market)
    reflection = build_strategy_reflection(
        outcomes,
        shadow_runs,
        market=args.market,
        as_of_date=args.as_of_date,
        horizon_days=args.horizon_days,
    )
    return reflection, build_policy_candidate(reflection)


def main() -> int:
    args = _parse_args()
    if not _enabled():
        print("[strategy_reflection] disabled; set WYCKOFF_STRATEGY_REFLECTION=shadow to enable")
        return 0
    reflection, candidate = _build_payloads(args)
    if args.dry_run:
        print(json.dumps({"reflection": reflection, "candidate": candidate}, ensure_ascii=False, indent=2))
        return 0
    reflection_written = upsert_strategy_reflection(reflection)
    candidate_written = upsert_strategy_policy_candidate(candidate)
    print(
        "[strategy_reflection] written: "
        f"reflection={reflection_written}, candidate={candidate_written}, status={reflection['status']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
