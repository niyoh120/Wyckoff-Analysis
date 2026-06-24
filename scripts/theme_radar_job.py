"""CLI entrypoint for strategic theme radar reports."""

from __future__ import annotations

import argparse

import _bootstrap  # noqa: F401

from workflows.theme_radar_runtime import (
    notify_theme_radar_report,
    run_theme_radar,
    write_theme_radar_artifacts,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run strategic theme radar")
    parser.add_argument("--with-news", action="store_true", help="collect optional public news/GDELT events")
    parser.add_argument("--no-persist", action="store_true", help="skip local SQLite snapshot persistence")
    parser.add_argument("--output", default="logs/theme_radar_report.md", help="markdown output path")
    parser.add_argument(
        "--html-output", default="logs/theme_radar_report.html", help="html output path; empty disables html"
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    snapshot = run_theme_radar(with_news=args.with_news, persist=not args.no_persist)
    artifacts = write_theme_radar_artifacts(snapshot, output=args.output, html_output=args.html_output)
    notification = notify_theme_radar_report(snapshot, artifacts.report)
    print(f"[theme_radar] wrote markdown: {artifacts.markdown_path}")
    if artifacts.html_path:
        print(f"[theme_radar] wrote html: {artifacts.html_path}")
    print(f"[theme_radar] notification: {notification.reason}")
    return 0 if not notification.attempted or notification.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
