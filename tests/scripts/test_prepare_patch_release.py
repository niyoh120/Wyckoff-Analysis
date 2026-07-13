from pathlib import Path

import pytest

from scripts.prepare_patch_release import next_patch_version, update_project_version, version_tuple


def test_next_patch_uses_newer_pypi_version():
    assert next_patch_version("0.9.156", "0.9.158") == "0.9.159"


def test_next_patch_uses_newer_project_version():
    assert next_patch_version("1.2.3", "1.1.99") == "1.2.4"


def test_version_tuple_rejects_prerelease():
    with pytest.raises(ValueError, match="major.minor.patch"):
        version_tuple("1.2.3rc1")


def test_update_project_version_changes_only_project_version(tmp_path: Path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\nname = "demo"\nversion = "1.2.3"\n\n[tool.demo]\nversion = "keep"\n', encoding="utf-8"
    )

    update_project_version(pyproject, "1.2.4")

    assert pyproject.read_text(encoding="utf-8").count('version = "1.2.4"') == 1
    assert 'version = "keep"' in pyproject.read_text(encoding="utf-8")
