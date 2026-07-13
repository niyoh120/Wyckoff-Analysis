#!/usr/bin/env python3
"""Select the next PyPI patch version and apply it to pyproject.toml."""

from __future__ import annotations

import argparse
import json
import re
import tomllib
import urllib.request
from pathlib import Path

PYPI_JSON_URL = "https://pypi.org/pypi/{package}/json"
VERSION_PATTERN = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pyproject", type=Path, default=Path("pyproject.toml"))
    parser.add_argument("--latest-version", default="", help="Override PyPI lookup, mainly for deterministic tests")
    return parser.parse_args()


def version_tuple(value: str) -> tuple[int, int, int]:
    match = VERSION_PATTERN.fullmatch(str(value).strip())
    if not match:
        raise ValueError(f"仅支持稳定的 major.minor.patch 版本，收到: {value}")
    return tuple(int(part) for part in match.groups())


def next_patch_version(project_version: str, published_version: str) -> str:
    major, minor, patch = max(version_tuple(project_version), version_tuple(published_version))
    return f"{major}.{minor}.{patch + 1}"


def published_version(package: str) -> str:
    request = urllib.request.Request(
        PYPI_JSON_URL.format(package=package),
        headers={"Accept": "application/json", "User-Agent": "wyckoff-pypi-release/1"},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return str(json.load(response)["info"]["version"])


def update_project_version(path: Path, version: str) -> None:
    content = path.read_text(encoding="utf-8")
    updated, count = re.subn(r'(?m)^(version\s*=\s*")[^"]+("\s*)$', rf"\g<1>{version}\g<2>", content, count=1)
    if count != 1:
        raise ValueError(f"无法在 {path} 中唯一定位 project.version")
    path.write_text(updated, encoding="utf-8")


def main() -> int:
    args = parse_args()
    with args.pyproject.open("rb") as handle:
        project = tomllib.load(handle)["project"]
    latest = args.latest_version.strip() or published_version(str(project["name"]))
    version = next_patch_version(str(project["version"]), latest)
    update_project_version(args.pyproject, version)
    print(version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
