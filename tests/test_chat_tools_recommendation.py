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


def test_query_history_attribution_surfaces_policy_governor(monkeypatch):
    from agents import history_tools

    monkeypatch.setenv("FUNNEL_DYNAMIC_POLICY", "shadow")
    monkeypatch.setattr(
        history_tools,
        "_load_attribution_rows",
        lambda limit, tool_context: [
            {
                "report_date": "2026-07-04",
                "window_start": "2026-05-05",
                "window_end": "2026-07-04",
                "shadow_diff_stats_json": {
                    "count": 12,
                    "avg_added": 1.4,
                    "avg_removed": 1.1,
                    "policy_governor": {
                        "status": "candidate",
                        "mode_recommendation": "review_promote_dynamic_policy",
                        "auto_apply": False,
                        "summary": "shadow 新增组显著优于移除组",
                        "horizon": "5",
                    },
                },
                "recommendations_json": [
                    {"type": "policy_governor", "target": "dynamic_policy", "horizon": "5", "reason": "{}"},
                    {
                        "type": "downweight",
                        "target": "lps",
                        "horizon": "5",
                        "reason": (
                            '{"action":"downweight","weight_multiplier":0.5,"evidence":{"avg_return_pct":-3.0}}'
                        ),
                    },
                ],
            }
        ],
    )

    result = query_history(source="attribution", limit=1)

    assert result["latest_policy"]["status"] == "candidate"
    assert result["latest_execution_state"]["scope"] == "tail_buy_and_funnel_shadow"
    assert result["records"][0]["shadow"]["runs"] == 12
    assert result["records"][0]["execution_state"]["signal_action_count"] == 1
    assert "漏斗动态策略 shadow 对照" in result["records"][0]["execution_state"]["summary"]
    assert result["records"][0]["signal_actions"] == [
        {
            "action": "downweight",
            "horizon": "5",
            "target": "lps",
            "weight_multiplier": 0.5,
            "evidence": {"avg_return_pct": -3.0},
        }
    ]


def test_query_history_attribution_uses_workflow_default_when_env_missing(monkeypatch, tmp_path):
    from agents import history_tools
    from workflows import strategy_attribution_execution

    monkeypatch.delenv("FUNNEL_DYNAMIC_POLICY", raising=False)
    workflow_path = tmp_path / "wyckoff_funnel.yml"
    workflow_path.write_text(
        "env:\n"
        "  FUNNEL_DYNAMIC_POLICY: "
        "${{ vars.FUNNEL_DYNAMIC_POLICY || secrets.FUNNEL_DYNAMIC_POLICY || 'shadow' }}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(strategy_attribution_execution, "DEFAULT_FUNNEL_WORKFLOW_PATH", workflow_path)
    monkeypatch.setattr(
        history_tools,
        "_load_attribution_rows",
        lambda limit, tool_context: [
            {
                "report_date": "2026-07-04",
                "window_start": "2026-05-05",
                "window_end": "2026-07-04",
                "shadow_diff_stats_json": {
                    "policy_governor": {
                        "status": "candidate",
                        "mode_recommendation": "review_promote_dynamic_policy",
                        "auto_apply": False,
                        "summary": "shadow 新增组显著优于移除组",
                        "horizon": "5",
                    },
                },
                "recommendations_json": [
                    {
                        "type": "downweight",
                        "target": "lps",
                        "horizon": "5",
                        "reason": '{"action":"downweight","weight_multiplier":0.5}',
                    },
                ],
            }
        ],
    )

    result = query_history(source="attribution", limit=1)

    state = result["latest_execution_state"]
    assert state["funnel_dynamic_policy"] == "shadow"
    assert state["scope"] == "tail_buy_and_funnel_shadow"


def test_query_attribution_exposes_policy_governor(monkeypatch):
    from integrations import supabase_base

    monkeypatch.setenv("FUNNEL_DYNAMIC_POLICY", "on")

    class FakeQuery:
        def __init__(self, rows):
            self.rows = rows

        def select(self, *_args, **_kwargs):
            return self

        def eq(self, *_args, **_kwargs):
            return self

        def order(self, *_args, **_kwargs):
            return self

        def limit(self, *_args, **_kwargs):
            return self

        def execute(self):
            return type("Result", (), {"data": self.rows})()

    class FakeClient:
        def table(self, _name):
            return FakeQuery(
                [
                    {
                        "report_date": "2026-07-04",
                        "window_start": "2026-05-05",
                        "window_end": "2026-07-04",
                        "shadow_diff_stats_json": {
                            "count": 24,
                            "avg_added": 0.42,
                            "avg_removed": 12.83,
                            "policy_governor": {
                                "status": "candidate",
                                "mode_recommendation": "review_promote_dynamic_policy",
                                "auto_apply": False,
                                "summary": "shadow 新增组显著优于移除组",
                                "horizon": "5",
                            },
                        },
                        "recommendations_json": [
                            {
                                "type": "downweight",
                                "horizon": "5",
                                "target": "lps",
                                "reason": '{"weight_multiplier": 0.5, "evidence": {"avg_return_pct": -3.2}}',
                            }
                        ],
                    }
                ]
            )

    monkeypatch.setattr(supabase_base, "create_read_client", lambda: FakeClient())

    result = query_history(source="attribution", limit=1)

    assert result["latest_policy"]["status"] == "candidate"
    assert result["latest_execution_state"]["scope"] == "tail_buy_and_funnel"
    assert result["records"][0]["policy_governor"]["mode_recommendation"] == "review_promote_dynamic_policy"
    assert result["records"][0]["signal_actions"][0]["target"] == "lps"
    assert "漏斗正式候选" in result["records"][0]["execution_state"]["summary"]
    assert result["records"][0]["shadow"]["runs"] == 24


def test_query_history_schema_allows_attribution_source():
    from cli.tools import TOOL_SCHEMAS

    query_schema = next(item for item in TOOL_SCHEMAS if item["name"] == "query_history")
    source = query_schema["parameters"]["properties"]["source"]

    assert "attribution" in source["enum"]
