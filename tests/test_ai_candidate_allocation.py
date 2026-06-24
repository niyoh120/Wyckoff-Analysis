"""AI candidate allocation policy tests."""

from __future__ import annotations

from core.ai_candidate_allocation import (
    AiCandidateAllocationConfig,
    allocate_ai_candidates,
    resolve_ai_candidate_policy,
)
from core.wyckoff_engine import FunnelResult
from workflows.ai_candidate_allocation_config import ai_candidate_allocation_config_from_env


class TestAllocateAiCandidates:
    def test_bear_rebound_uses_defensive_quota_family(self):
        config = AiCandidateAllocationConfig(
            total_cap=8,
            quota_by_family={"BEAR_REBOUND": (1, 2)},
        )

        policy = resolve_ai_candidate_policy("BEAR_REBOUND", config=config)

        assert policy["quota_family"] == "BEAR_REBOUND"
        assert policy["trend_quota"] == 1
        assert policy["accum_quota"] == 2

    def test_bear_rebound_default_quota_blocks_ai_candidates(self):
        policy = resolve_ai_candidate_policy("BEAR_REBOUND")

        assert policy["quota_family"] == "BEAR_REBOUND"
        assert policy["trend_quota"] == 0
        assert policy["accum_quota"] == 0

    def test_allocation_env_loader_stays_in_workflow_layer(self, monkeypatch):
        monkeypatch.setenv("FUNNEL_AI_TOTAL_CAP", "6")
        monkeypatch.setenv("FUNNEL_AI_RISK_ON_TREND", "4")
        monkeypatch.setenv("FUNNEL_AI_RISK_ON_ACCUM", "2")

        config = ai_candidate_allocation_config_from_env()
        policy = resolve_ai_candidate_policy("RISK_ON", config=config)

        assert policy["total_cap"] == 6
        assert policy["trend_quota"] == 4
        assert policy["accum_quota"] == 2

    def test_evr_and_compression_only_hits_enter_quota_tracks(self):
        result = FunnelResult(
            layer1_symbols=["000001", "000002"],
            layer2_symbols=["000001", "000002"],
            layer3_symbols=["000001", "000002"],
            top_sectors=[],
            triggers={"evr": [("000001", 2.0)], "compression": [("000002", 0.4)]},
            stage_map={},
            markup_symbols=[],
            exit_signals={},
            channel_map={},
            leader_radar_symbols=[],
            leader_radar_rows=[],
        )

        trend, accum, scores = allocate_ai_candidates(
            result,
            [],
            "NEUTRAL",
            policy_override={
                "total_cap": 2,
                "trend_quota": 1,
                "accum_quota": 1,
                "max_trend_l3_fill": 0,
                "max_accum_l3_fill": 0,
            },
        )

        assert trend == ["000001"]
        assert accum == ["000002"]
        assert scores["000001"] > 0
        assert scores["000002"] > 0

    def test_sos_outranks_evr_after_downweight_iteration(self):
        result = FunnelResult(
            layer1_symbols=["000001", "000002"],
            layer2_symbols=["000001", "000002"],
            layer3_symbols=["000001", "000002"],
            top_sectors=[],
            triggers={"sos": [("000001", 4.0)], "evr": [("000002", 4.0)]},
            stage_map={},
            markup_symbols=[],
            exit_signals={},
            channel_map={"000001": "点火破局", "000002": "趋势延续"},
            leader_radar_symbols=[],
            leader_radar_rows=[],
        )

        _trend, _accum, scores = allocate_ai_candidates(
            result,
            [],
            "NEUTRAL",
            policy_override={
                "total_cap": 2,
                "trend_quota": 2,
                "accum_quota": 0,
                "max_trend_l3_fill": 0,
                "max_accum_l3_fill": 0,
            },
        )

        assert scores["000001"] > scores["000002"]
