"""CLI entrypoint for database maintenance."""

from __future__ import annotations

import argparse

import _bootstrap  # noqa: F401

from workflows.db_maintenance import DbMaintenanceRequest, run_db_maintenance


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="数据库维护 — 多表过期数据清理")
    parser.add_argument("--dry-run", action="store_true", help="只查询待清理行数，不实际删除")
    return parser.parse_args()


def main() -> int:
    return run_db_maintenance(DbMaintenanceRequest(dry_run=parse_args().dry_run))


if __name__ == "__main__":
    raise SystemExit(main())
