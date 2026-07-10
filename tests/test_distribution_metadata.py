from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CONFIG = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_mcp_entrypoint_module_is_included_in_distribution():
    module = CONFIG["project"]["scripts"]["wyckoff-mcp"].partition(":")[0]
    py_modules = CONFIG["tool"]["setuptools"].get("py-modules", [])

    assert (ROOT / f"{module}.py").is_file()
    assert module in py_modules


@pytest.mark.parametrize(
    ("destination", "source"),
    [
        ("share/youngcan-wyckoff-analysis/data", "data/stock_list_cache.json"),
        ("share/youngcan-wyckoff-analysis", "CHANGELOG.md"),
        ("share/youngcan-wyckoff-analysis/config/profiles", "config/profiles/a_share_prod.yml"),
    ],
)
def test_runtime_resource_is_included_in_distribution(destination: str, source: str):
    assert (ROOT / source).is_file()
    assert source in CONFIG["tool"]["setuptools"]["data-files"].get(destination, [])
