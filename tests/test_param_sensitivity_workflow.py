from __future__ import annotations

import pandas as pd

from workflows.param_sensitivity import ParamSensitivityRequest, run_param_sensitivity_request


def test_run_param_sensitivity_request_writes_outputs(monkeypatch, tmp_path) -> None:
    import workflows.param_sensitivity as workflow

    monkeypatch.setattr(
        workflow,
        "run_sensitivity",
        lambda *_args, **_kwargs: pd.DataFrame(
            [
                {
                    "trades": 1,
                    "sharpe_ratio": 0.8,
                    "win_rate_pct": 60.0,
                    "avg_ret_pct": 2.5,
                    "hold_days": 10,
                    "stop_loss_pct": -8.0,
                    "take_profit_pct": 15.0,
                    "trailing_stop_pct": 0.0,
                    "trailing_activate_pct": 0.0,
                    "top_n": 3,
                }
            ]
        ),
    )

    result = run_param_sensitivity_request(
        ParamSensitivityRequest(start="2026-01-01", end="2026-01-31", output_dir=str(tmp_path))
    )

    assert result == 0
    assert len(list(tmp_path.glob("sensitivity_*.csv"))) == 1
    assert len(list(tmp_path.glob("sensitivity_*.md"))) == 1
