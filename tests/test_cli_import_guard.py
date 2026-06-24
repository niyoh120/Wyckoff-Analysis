from pathlib import Path


def test_cli_entry_prefers_packaged_core(monkeypatch, tmp_path):
    fake_core = tmp_path / "core"
    fake_core.mkdir()
    (fake_core / "__init__.py").write_text("# shadow package\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))

    import cli.__main__  # noqa: F401
    import core.candidate_ranker as candidate_ranker

    expected_root = Path(__file__).resolve().parents[1] / "core"
    assert Path(candidate_ranker.__file__).resolve().parent == expected_root
