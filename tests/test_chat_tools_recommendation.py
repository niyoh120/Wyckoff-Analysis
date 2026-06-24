from __future__ import annotations

from agents.history_tools import query_history


def test_query_recommendation_exposes_non_ai_review_role(monkeypatch):
    from integrations import local_db

    monkeypatch.setattr(
        local_db,
        "load_recommendations",
        lambda limit: [
            {
                "code": "603039",
                "name": "泛微网络",
                "recommend_date": "20260611",
                "is_ai_recommended": False,
            }
        ],
    )

    result = query_history(source="recommendation", limit=1)

    assert result["records"][0]["is_ai_recommended"] is False
    assert result["records"][0]["entry_role"] == "观察/信号复盘"


def test_query_recommendation_exposes_ai_recommendation_role(monkeypatch):
    from integrations import local_db

    monkeypatch.setattr(
        local_db,
        "load_recommendations",
        lambda limit: [
            {
                "code": "300557",
                "name": "理工光科",
                "recommend_date": "20260615",
                "is_ai_recommended": "true",
            }
        ],
    )

    result = query_history(source="recommendation", limit=1)

    assert result["records"][0]["is_ai_recommended"] is True
    assert result["records"][0]["entry_role"] == "AI推荐"
