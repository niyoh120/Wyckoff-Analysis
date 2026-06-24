from __future__ import annotations


def test_recommendation_reprice_job_refreshes_cn_and_tail_buy(monkeypatch):
    import workflows.recommendation_tracking_reprice_job as job

    calls: list[str] = []
    monkeypatch.setattr(
        job,
        "refresh_tracking_prices_with_tickflow_realtime",
        lambda: calls.append("cn") or _summary(rows_total=3, rows_updated=2),
    )
    monkeypatch.setattr(
        job,
        "refresh_tail_buy_prices_with_tickflow_realtime",
        lambda: calls.append("tail") or _summary(rows_total=2, rows_updated=1),
    )

    result = job.run_recommendation_reprice_job(job.RecommendationRepriceRequest(market="cn"))

    assert result == 0
    assert calls == ["cn", "tail"]


def test_recommendation_reprice_job_uses_global_market_path(monkeypatch):
    import workflows.recommendation_tracking_reprice_job as job

    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(job, "refresh_tracking_prices_with_tickflow_realtime", lambda: calls.append(("cn", "")) or {})
    monkeypatch.setattr(job, "refresh_tail_buy_prices_with_tickflow_realtime", lambda: calls.append(("tail", "")) or {})
    monkeypatch.setattr(
        job,
        "refresh_global_tracking_prices",
        lambda market: calls.append(("global", market)) or _summary(rows_total=1, rows_updated=1),
    )

    result = job.run_recommendation_reprice_job(job.RecommendationRepriceRequest(market="us"))

    assert result == 0
    assert calls == [("global", "us")]


def _summary(**overrides):
    summary = {
        "rows_total": 0,
        "rows_updated": 0,
        "rows_skipped": 0,
        "codes_total": 0,
        "codes_no_data": 0,
        "latest_trade_date": "20260622",
    }
    summary.update(overrides)
    return summary
