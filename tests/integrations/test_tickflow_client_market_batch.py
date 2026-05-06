from __future__ import annotations

from integrations.tickflow_client import TickFlowClient


def test_get_quotes_accepts_universe(monkeypatch):
    client = TickFlowClient(api_key="test-key")
    calls = []

    def fake_request(path, *, params=None):
        calls.append((path, params))
        return {"data": [{"symbol": "AAPL.US", "last_price": 205.0}]}

    monkeypatch.setattr(client, "_request", fake_request)

    quotes = client.get_quotes(universes=["US_Equity"])

    assert calls == [("/v1/quotes", {"universes": "US_Equity"})]
    assert quotes["AAPL.US"]["last_price"] == 205.0


def test_get_klines_batch_parses_payload(monkeypatch):
    client = TickFlowClient(api_key="test-key")
    calls = []

    def fake_request(path, *, params=None):
        calls.append((path, params))
        return {
            "data": {
                "AAPL.US": {
                    "timestamp": [1704067200000, 1704153600000],
                    "open": [100.0, 101.0],
                    "high": [102.0, 103.0],
                    "low": [99.0, 100.0],
                    "close": [101.0, 102.0],
                    "prev_close": [99.0, 101.0],
                    "volume": [1000, 1200],
                    "amount": [101000.0, 122400.0],
                }
            }
        }

    monkeypatch.setattr(client, "_request", fake_request)

    result = client.get_klines_batch(["AAPL.US"], period="1d", count=2, adjust="forward")

    assert calls == [
        (
            "/v1/klines/batch",
            {"symbols": "AAPL.US", "period": "1d", "count": 2, "adjust": "forward"},
        )
    ]
    assert list(result) == ["AAPL.US"]
    assert result["AAPL.US"]["close"].tolist() == [101.0, 102.0]
