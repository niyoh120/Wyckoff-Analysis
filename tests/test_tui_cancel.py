from __future__ import annotations

from cli.tui import _should_force_exit_busy_cancel


def test_busy_cancel_requires_existing_cancel_signal():
    assert not _should_force_exit_busy_cancel(False, 10.0, 10.2)


def test_busy_cancel_second_press_forces_exit_inside_window():
    assert _should_force_exit_busy_cancel(True, 10.0, 11.0)


def test_busy_cancel_second_press_outside_window_retries_cancel():
    assert not _should_force_exit_busy_cancel(True, 10.0, 12.0)
