from __future__ import annotations

from types import SimpleNamespace

from workflows.step3_rag import _build_step3_rag_summary_lines, _collect_step3_rag_results


def _result(*, relevant: int, hits: list[str]):
    return SimpleNamespace(
        raw_result_count=3,
        relevant_result_count=relevant,
        hits=hits,
        semantic_checked=False,
        error=None,
        veto=False,
        search_source="test",
        elapsed_ms=1,
    )


def test_rag_summary_does_not_treat_relevant_news_as_negative_keyword_hit(capsys) -> None:
    _, _, stats = _collect_step3_rag_results(
        {
            "000001": _result(relevant=2, hits=[]),
            "000002": _result(relevant=1, hits=["立案调查"]),
        }
    )

    lines = _build_step3_rag_summary_lines(stats, 0)

    assert "- 相关新闻覆盖: 2/2" in lines
    assert "- 命中负面关键词: 1/2" in lines
    capsys.readouterr()
