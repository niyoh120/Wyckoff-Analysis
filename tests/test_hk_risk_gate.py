from __future__ import annotations

import pandas as pd

from workflows.hk_risk_gate import apply_hk_risk_gate


def _frame(closes: list[float], *, opens: list[float] | None = None, amount: float = 20_000_000.0) -> pd.DataFrame:
    dates = pd.date_range("2025-01-01", periods=len(closes), freq="B")
    opens = opens or closes
    return pd.DataFrame(
        {
            "date": dates.strftime("%Y-%m-%d"),
            "open": opens,
            "close": closes,
            "amount": [amount] * len(closes),
            "pct_chg": pd.Series(closes).pct_change().fillna(0.0) * 100.0,
        }
    )


class TestApplyHkRiskGate:
    def test_clean_symbol_kept(self):
        df_map = {"00700.HK": _frame([300.0, 305.0, 310.0])}
        kept, blocked = apply_hk_risk_gate(["00700.HK"], df_map)
        assert kept == ["00700.HK"]
        assert blocked == {}

    def test_penny_stock_blocked(self):
        df_map = {"00099.HK": _frame([0.5, 0.5, 0.45])}
        kept, blocked = apply_hk_risk_gate(["00099.HK"], df_map)
        assert kept == []
        assert "00099.HK" in blocked
        assert "仙股" in blocked["00099.HK"]

    def test_illiquid_symbol_blocked(self):
        df_map = {"08001.HK": _frame([10.0, 10.2, 10.1], amount=100_000.0)}
        kept, blocked = apply_hk_risk_gate(["08001.HK"], df_map)
        assert kept == []
        assert "流动性" in blocked["08001.HK"]

    def test_extreme_move_blocked(self):
        df_map = {"00088.HK": _frame([10.0, 10.2, 25.0])}
        kept, blocked = apply_hk_risk_gate(["00088.HK"], df_map)
        assert kept == []
        assert "00088.HK" in blocked

    def test_missing_history_kept_by_default(self):
        kept, blocked = apply_hk_risk_gate(["00700.HK"], {})
        assert kept == ["00700.HK"]
        assert blocked == {}

    def test_mixed_symbols_partial_block(self):
        df_map = {
            "00700.HK": _frame([300.0, 305.0, 310.0]),
            "00099.HK": _frame([0.5, 0.5, 0.45]),
        }
        kept, blocked = apply_hk_risk_gate(["00700.HK", "00099.HK"], df_map)
        assert kept == ["00700.HK"]
        assert list(blocked) == ["00099.HK"]
