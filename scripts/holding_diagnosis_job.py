"""CLI entrypoint for holding diagnosis."""

from __future__ import annotations

import _bootstrap  # noqa: F401

from workflows.holding_diagnosis_job import run_holding_diagnosis_job


def main() -> int:
    return run_holding_diagnosis_job()


if __name__ == "__main__":
    raise SystemExit(main())
