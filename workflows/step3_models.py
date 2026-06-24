"""Step3 report workflow data contracts."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from workflows.step3_runtime_config import Step3RuntimeConfig


@dataclass(frozen=True)
class Step3RunOptions:
    webhook_url: str
    api_key: str
    model: str
    notify: bool
    provider: str
    llm_base_url: str
    wecom_webhook: str
    dingtalk_webhook: str
    runtime_config: Step3RuntimeConfig


@dataclass(frozen=True)
class Step3MarketContext:
    window: object
    benchmark_context: dict
    regime: str
    sector_rotation_ctx: dict
    sector_rotation_map: dict
    sector_map: dict
    market_cap_map: dict
    financial_map: dict[str, dict]
    benchmark_ret_10: float | None


@dataclass(frozen=True)
class Step3CandidateBundle:
    candidates_df: pd.DataFrame
    code_to_df: dict[str, pd.DataFrame]
    failed: list[tuple[str, str]]


@dataclass(frozen=True)
class Step3RagResult:
    selected_df: pd.DataFrame
    preview: str
    veto_lines: list[str]


@dataclass(frozen=True)
class Step3TrackInputs:
    payloads_by_track: dict[str, list[str]]
    df_by_track: dict[str, pd.DataFrame]
    selected_codes_by_track: dict[str, list[str]]
    items_by_track: dict[str, list[dict]]


@dataclass(frozen=True)
class Step3TrackPlan:
    track_inputs: Step3TrackInputs
    track_requests: list[dict]
    active_tracks: list[str]


@dataclass(frozen=True)
class Step3LlmResult:
    ok: bool
    status: str
    report: str
    used_models: dict[str, str]


@dataclass(frozen=True)
class Step3SelectionState:
    market_context: Step3MarketContext
    candidate_bundle: Step3CandidateBundle
    selected_df: pd.DataFrame
    rag_result: Step3RagResult
