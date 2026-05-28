#!/usr/bin/env python3
"""Trigger the Tail Buy GitHub Actions workflow."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

REPO = "YoungCan-Wang/WyckoffTradingAgent"
WORKFLOW_FILE = "tail_buy_1420.yml"
DEFAULT_REF = "main"
TRIGGER_FILE = Path(".github/triggers/tail-buy")


def _github_token() -> str:
    for key in ("GITHUB_PAT", "GH_TOKEN", "GITHUB_TOKEN"):
        value = os.getenv(key, "").strip()
        if value:
            return value
    return ""


def _dispatch_with_api(token: str, ref: str) -> int:
    url = f"https://api.github.com/repos/{REPO}/actions/workflows/{WORKFLOW_FILE}/dispatches"
    req = urllib.request.Request(
        url,
        data=json.dumps({"ref": ref}).encode(),
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            print(f"Tail Buy workflow dispatched on {ref} (HTTP {resp.status})")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        print(f"API dispatch failed: HTTP {exc.code}\n{body}", file=sys.stderr)
        return 1
    return 0


def _dispatch_with_push(ref: str) -> int:
    root = Path(__file__).resolve().parent.parent
    trigger_path = root / TRIGGER_FILE
    trigger_path.parent.mkdir(parents=True, exist_ok=True)
    trigger_path.write_text(f"{datetime.now(UTC).isoformat()}\n", encoding="utf-8")
    rel = TRIGGER_FILE.as_posix()
    subprocess.run(["git", "add", rel], cwd=root, check=True)
    subprocess.run(
        ["git", "commit", "-m", "chore: trigger Tail Buy workflow"],
        cwd=root,
        check=True,
    )
    push = subprocess.run(["git", "push", "origin", f"HEAD:{ref}"], cwd=root)
    if push.returncode != 0:
        print("Push trigger failed; ensure git push access to main.", file=sys.stderr)
        return 1
    print(f"Tail Buy remote trigger pushed to {ref}")
    return 0


def main() -> int:
    ref = os.getenv("TAIL_BUY_WORKFLOW_REF", DEFAULT_REF).strip() or DEFAULT_REF
    token = _github_token()
    if token:
        return _dispatch_with_api(token, ref)
    if os.getenv("TAIL_BUY_TRIGGER_MODE", "auto").strip().lower() == "api":
        print("Set GITHUB_PAT (or GH_TOKEN) with repo actions:write to dispatch Tail Buy.", file=sys.stderr)
        return 1
    return _dispatch_with_push(ref)


if __name__ == "__main__":
    sys.exit(main())
