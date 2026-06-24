from integrations.recommendation_tracking_common import resolve_tickflow_quote_price
from workflows.tail_buy_holdings import resolve_quote_price


def test_recommendation_quote_price_prefers_tickflow_last_price() -> None:
    price = resolve_tickflow_quote_price({"last_price": 42.35, "open": 41.35, "prev_close": 41.91})

    assert price == 42.35


def test_tail_buy_quote_price_does_not_fallback_to_open() -> None:
    assert resolve_quote_price({"open": 41.35, "prev_close": 41.91}) == 0.0
    assert resolve_quote_price({"last_price": 42.35, "open": 41.35}) == 42.35
