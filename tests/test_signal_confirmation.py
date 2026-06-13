from __future__ import annotations

from core.signal_confirmation import check_confirmation


def test_sos_confirmation_requires_reclaiming_signal_close():
    snap = {"snap_low": 9.2, "snap_close": 10.0, "snap_volume": 1_000_000}

    status, reason = check_confirmation(
        "sos",
        snap,
        {"low": 9.4, "close": 9.8, "volume": 700_000},
        days_elapsed=1,
    )

    assert status == "pending"
    assert "等待缩量确认" in reason


def test_sos_confirmation_accepts_shrinkage_above_signal_close():
    snap = {"snap_low": 9.2, "snap_close": 10.0, "snap_volume": 1_000_000}

    status, reason = check_confirmation(
        "sos",
        snap,
        {"low": 9.4, "close": 10.05, "volume": 700_000},
        days_elapsed=1,
    )

    assert status == "confirmed"
    assert "信号日收盘" in reason
