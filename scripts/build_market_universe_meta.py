"""CLI entrypoint for market universe metadata generation."""

from __future__ import annotations

import argparse
from pathlib import Path

import _bootstrap  # noqa: F401

from workflows.market_universe_meta import (
    DEFAULT_UNIVERSE_DIR,
    MarketUniverseMetaRequest,
    run_market_universe_meta_build,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build market universe metadata JSON files.")
    parser.add_argument("--universe-dir", type=Path, default=DEFAULT_UNIVERSE_DIR)
    return parser.parse_args()


def main() -> int:
    return run_market_universe_meta_build(MarketUniverseMetaRequest(universe_dir=parse_args().universe_dir))


if __name__ == "__main__":
    raise SystemExit(main())
