"""CLI entrypoint for updating the market-cycle backtest report."""

from __future__ import annotations

import argparse
from pathlib import Path

import _bootstrap  # noqa: F401

from workflows.backtest_market_report_artifacts import load_grid_cells
from workflows.backtest_market_report_builder import build_report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Update docs/BACKTEST_MARKET_REPORT.md from backtest grid artifacts.")
    parser.add_argument("--artifacts-dir", default="artifacts", help="Directory containing backtest-grid-* artifacts")
    parser.add_argument("--output", default="docs/BACKTEST_MARKET_REPORT.md", help="Report markdown path")
    parser.add_argument("--run-url", default="", help="GitHub Actions run URL")
    parser.add_argument("--generated-at", default="", help="Override generated timestamp")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cells = load_grid_cells(Path(args.artifacts_dir))
    report = build_report(cells, run_url=args.run_url, generated_at=args.generated_at)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report + "\n", encoding="utf-8")
    print(f"[backtest-report] wrote {out_path} from {len(cells)} grid cells")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
