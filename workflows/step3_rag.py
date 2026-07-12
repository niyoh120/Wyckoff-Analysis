"""Step3 negative-news RAG veto workflow."""

from __future__ import annotations

import pandas as pd

from integrations.rag_veto import (
    RAG_SEMANTIC_MODEL,
    get_rag_veto_runtime_status,
    is_rag_veto_enabled,
    run_negative_news_veto,
)
from workflows.step3_models import Step3RagResult
from workflows.step3_runtime_config import Step3RuntimeConfig


def apply_step3_rag_veto(selected_df: pd.DataFrame, runtime_config: Step3RuntimeConfig) -> Step3RagResult:
    rag_skip_reason = ""
    if runtime_config.enable_rag_veto and not selected_df.empty:
        rag_status = get_rag_veto_runtime_status()
        if bool(rag_status.get("enabled")):
            return _run_rag_veto(selected_df, rag_status)
        print("[step3][rag] 已关闭（RAG_VETO_ENABLED=0）")
        rag_skip_reason = "RAG_VETO_ENABLED=0"
    elif runtime_config.enable_rag_veto:
        rag_skip_reason = _rag_skip_reason(selected_df)
    return _skipped_rag_result(selected_df, runtime_config, rag_skip_reason)


def _run_rag_veto(selected_df: pd.DataFrame, rag_status: dict) -> Step3RagResult:
    rag_inputs = [
        {"code": str(row.get("code", "")).strip(), "name": str(row.get("name", ""))}
        for _, row in selected_df.iterrows()
    ]
    print(
        f"[step3][rag] 启动：candidates={len(rag_inputs)}, "
        f"source={rag_status.get('source', 'akshare')}, "
        f"lookback_days={rag_status.get('lookback_days')}, "
        f"workers={rag_status.get('max_workers')}"
    )
    veto_map = run_negative_news_veto(rag_inputs)
    vetoed_codes, rag_veto_lines, stats = _collect_step3_rag_results(veto_map)
    rag_summary_lines = _build_step3_rag_summary_lines(stats, len(vetoed_codes))
    if not vetoed_codes:
        print("[step3][rag] 未命中负面关键词，保持候选不变")
        preview = "## 🛡️ RAG 防雷执行摘要（前置）\n" + "\n".join(rag_summary_lines) + "\n\n---\n"
        return Step3RagResult(selected_df=selected_df, preview=preview, veto_lines=[])
    return _vetoed_rag_result(selected_df, vetoed_codes, rag_veto_lines, rag_summary_lines)


def _collect_step3_rag_results(veto_map: dict) -> tuple[list[str], list[str], dict[str, int]]:
    vetoed_codes: list[str] = []
    rag_veto_lines: list[str] = []
    stats = {
        "scanned": len(veto_map),
        "external_ok": 0,
        "relevant": 0,
        "keyword_hits": 0,
        "semantic_checked": 0,
        "errors": 0,
    }
    for code, result in veto_map.items():
        _update_rag_stats(stats, result)
        hit_text = "、".join(result.hits[:5]) if result.hits else "-"
        _log_rag_result(code, result, hit_text)
        if result.veto:
            vetoed_codes.append(code)
            rag_veto_lines.append(_format_rag_veto_line(code, result, hit_text))
    return vetoed_codes, rag_veto_lines, stats


def _update_rag_stats(stats: dict[str, int], result) -> None:
    if int(result.raw_result_count or 0) > 0:
        stats["external_ok"] += 1
    if int(result.relevant_result_count or 0) > 0:
        stats["relevant"] += 1
    if result.hits:
        stats["keyword_hits"] += 1
    if bool(result.semantic_checked):
        stats["semantic_checked"] += 1
    if result.error:
        stats["errors"] += 1


def _log_rag_result(code: str, result, hit_text: str) -> None:
    print(
        "[step3][rag] "
        f"{code} source={result.search_source or '-'} "
        f"raw={int(result.raw_result_count or 0)} "
        f"relevant={int(result.relevant_result_count or 0)} "
        f"hits={hit_text} "
        f"veto={bool(result.veto)} "
        f"semantic_checked={bool(result.semantic_checked)} "
        f"elapsed_ms={int(result.elapsed_ms or 0)}" + (f" err={result.error}" if result.error else "")
    )


def _format_rag_veto_line(code: str, result, hit_text: str) -> str:
    ev_text = f" | 证据: {result.evidence[0]}" if result.evidence else ""
    semantic_text = ""
    if result.semantic_checked:
        semantic_text = f" | 语义判定: 极端负面={result.semantic_negative}" + (
            f"({result.semantic_reason})" if result.semantic_reason else ""
        )
    hit_label = hit_text if hit_text != "-" else "负面关键词"
    return f"- {code} {result.name}: 命中 {hit_label}{semantic_text}{ev_text}"


def _build_step3_rag_summary_lines(stats: dict[str, int], veto_count: int) -> list[str]:
    scanned = stats["scanned"]
    return [
        f"- 语义模型: {RAG_SEMANTIC_MODEL or '未配置'}",
        f"- 扫描股票: {scanned}",
        f"- 新闻拉取成功: {stats['external_ok']}/{scanned}" if scanned else "- 新闻拉取成功: 0/0",
        f"- 相关新闻覆盖: {stats['relevant']}/{scanned}" if scanned else "- 相关新闻覆盖: 0/0",
        f"- 命中负面关键词: {stats['keyword_hits']}/{scanned}" if scanned else "- 命中负面关键词: 0/0",
        f"- 语义二判执行: {stats['semantic_checked']}",
        f"- 拉取异常: {stats['errors']}",
        f"- veto 剔除: {veto_count}",
    ]


def _vetoed_rag_result(
    selected_df: pd.DataFrame,
    vetoed_codes: list[str],
    rag_veto_lines: list[str],
    rag_summary_lines: list[str],
) -> Step3RagResult:
    before_n = len(selected_df)
    selected_df = selected_df[~selected_df["code"].astype(str).isin(set(vetoed_codes))].reset_index(drop=True)
    print(f"[step3][rag] 负面新闻 veto: {before_n} -> {len(selected_df)}（剔除{len(vetoed_codes)}）")
    preview = (
        "## 🛡️ RAG 防雷执行摘要（前置）\n"
        + "\n".join(rag_summary_lines)
        + "\n\n## 🛑 RAG 防雷已剔除（前置）\n"
        + "\n".join(rag_veto_lines)
        + "\n\n---\n"
    )
    return Step3RagResult(selected_df=selected_df, preview=preview, veto_lines=rag_veto_lines)


def _rag_skip_reason(selected_df: pd.DataFrame) -> str:
    if selected_df.empty:
        print("[step3][rag] 跳过：候选为空")
        return "候选为空"
    if not is_rag_veto_enabled():
        print("[step3][rag] 跳过：RAG_VETO_ENABLED=0")
        return "RAG_VETO_ENABLED=0"
    print("[step3][rag] 跳过：未满足运行条件")
    return "未满足运行条件"


def _skipped_rag_result(
    selected_df: pd.DataFrame,
    runtime_config: Step3RuntimeConfig,
    rag_skip_reason: str,
) -> Step3RagResult:
    preview = ""
    if runtime_config.enable_rag_veto and rag_skip_reason:
        preview = f"## 🛡️ RAG 防雷执行摘要（前置）\n- 执行状态: 跳过\n- 原因: {rag_skip_reason}\n\n---\n"
    return Step3RagResult(selected_df=selected_df, preview=preview, veto_lines=[])
