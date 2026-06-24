"""CLI entrypoint for sector-continuity reports."""

from __future__ import annotations

from workflows.sector_continuity_runtime import (
    build_sector_continuity_result,
    notify_sector_continuity_report,
    resolve_sector_trade_date,
)


def main() -> int:
    trade_date = resolve_sector_trade_date()
    if trade_date is None:
        return 0
    result = build_sector_continuity_result(trade_date)
    if result is None:
        print("[sector_continuity] 无历史数据，跳过")
        return 0
    for message in result.messages:
        print(message)
    notification = notify_sector_continuity_report(result.report, trade_date)
    print(f"[sector_continuity] notification: {notification.reason}")
    return 0 if not notification.attempted or notification.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
