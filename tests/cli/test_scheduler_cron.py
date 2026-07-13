from __future__ import annotations

from datetime import datetime

from cli.scheduler import Schedule, cron_matches_now, next_scheduled_time, schedule_status


def test_cron_matches_now_uses_provided_time_instead_of_wall_clock():
    at = datetime(2026, 1, 5, 9, 25)  # Monday

    assert cron_matches_now("25 9 * * 1-5", at=at)
    assert not cron_matches_now("26 9 * * 1-5", at=at)


def test_cron_matches_now_checks_weekday_field():
    saturday = datetime(2026, 1, 3, 9, 25)

    assert not cron_matches_now("25 9 * * 1-5", at=saturday)


def test_schedule_status_includes_next_run_and_last_result():
    at = datetime(2026, 7, 13, 9, 24)
    schedule = Schedule(
        id="mkt-open",
        name="盘前风控检查",
        cron="25 9 * * 1-5",
        action="/checkup",
        last_fired="2026-07-10T09:25",
        last_status="triggered",
    )

    assert next_scheduled_time(schedule, at=at) == datetime(2026, 7, 13, 9, 25)
    assert schedule_status([schedule], at=at) == [
        {
            "id": "mkt-open",
            "name": "盘前风控检查",
            "enabled": True,
            "cron": "25 9 * * 1-5",
            "last_fired": "2026-07-10T09:25",
            "last_status": "triggered",
            "last_error": "",
            "next_run": "2026-07-13T09:25",
        }
    ]
