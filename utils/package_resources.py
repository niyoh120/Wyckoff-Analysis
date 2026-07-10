"""Resolve runtime resources in source checkouts and installed distributions."""

from __future__ import annotations

import os
import sys
import tomllib
from functools import cache
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path, PurePosixPath

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_SHARE_ROOT = Path(sys.prefix) / "share" / "youngcan-wyckoff-analysis"
_DISTRIBUTION_NAME = "youngcan-wyckoff-analysis"
_SOURCE_MARKER = PROJECT_ROOT / "pyproject.toml"


def _detect_source_checkout() -> bool:
    try:
        config = tomllib.loads(_SOURCE_MARKER.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return False
    return config.get("project", {}).get("name") == _DISTRIBUTION_NAME


_SOURCE_CHECKOUT = _detect_source_checkout()


@cache
def _distribution_resource(relative: str) -> Path | None:
    suffix = ("share", _DISTRIBUTION_NAME, *PurePosixPath(relative).parts)
    try:
        installed = distribution(_DISTRIBUTION_NAME)
    except PackageNotFoundError:
        return None
    for entry in installed.files or ():
        if PurePosixPath(str(entry)).parts[-len(suffix) :] != suffix:
            continue
        path = Path(installed.locate_file(entry)).resolve()
        if path.exists():
            return path
    return None


def runtime_resource(repo_relative: str | Path) -> Path:
    source_path = PROJECT_ROOT / repo_relative
    if _SOURCE_CHECKOUT and source_path.exists():
        return source_path
    return _distribution_resource(str(repo_relative)) or PACKAGE_SHARE_ROOT / repo_relative


def _installed_universe_dir() -> Path:
    for filename in (
        "aliases.json",
        "us_meta.json",
        "hk_meta.json",
        "etf_cn_meta.json",
        "us.txt",
        "hk.txt",
        "etf_cn.txt",
    ):
        path = _distribution_resource(f"market_universes/{filename}")
        if path:
            return path.parent
    return PACKAGE_SHARE_ROOT / "market_universes"


def market_universe_dirs() -> list[Path]:
    configured = os.getenv("MARKET_UNIVERSE_DIR", "").strip()
    candidates = []
    if configured:
        candidates.append(Path(configured).expanduser())
    if _SOURCE_CHECKOUT:
        candidates.append(PROJECT_ROOT / "data" / "market_universes")
    else:
        candidates.append(_installed_universe_dir())
    candidates.append(Path.cwd() / "data" / "market_universes")
    return list(dict.fromkeys(candidates))


def market_universe_dir(*filenames: str) -> Path:
    for directory in market_universe_dirs():
        if all((directory / filename).is_file() for filename in filenames):
            return directory
    if _SOURCE_CHECKOUT:
        return PROJECT_ROOT / "data" / "market_universes"
    return _installed_universe_dir()


def market_universe_path(filename: str) -> Path:
    return market_universe_dir(filename) / filename
