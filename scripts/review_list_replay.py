"""CLI entrypoint for limit-up miss replay."""

from __future__ import annotations

import os

from workflows.review_list_replay import run_review_list_replay


def main() -> int:
    return run_review_list_replay(os.getenv("FEISHU_WEBHOOK_URL", "").strip())


if __name__ == "__main__":
    raise SystemExit(main())
