from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

HELP_SCRIPTS = [
    "scripts/backtest_portfolio.py",
    "scripts/backtest_runner.py",
    "scripts/backtest_snapshot_fetch.py",
    "scripts/backtest_snapshot_fetch_us.py",
    "scripts/benchmark_funnel_fetch.py",
    "scripts/backfill_recommendation_tracking.py",
    "scripts/build_market_universe_meta.py",
    "scripts/daily_job.py",
    "scripts/db_maintenance.py",
    "scripts/diagnose_holdings.py",
    "scripts/evaluate_recommendation_events.py",
    "scripts/export_a_share_csv.py",
    "scripts/market_funnel_job.py",
    "scripts/param_sensitivity.py",
    "scripts/premarket_risk_job.py",
    "scripts/recommendation_tracking_reprice_job.py",
    "scripts/single_symbol_funnel_diagnosis.py",
    "scripts/step4_from_supabase.py",
    "scripts/theme_radar_job.py",
    "scripts/update_backtest_market_report.py",
    "scripts/us_recommendation_performance_job.py",
    "scripts/web_background_job.py",
]


@pytest.mark.parametrize("script", HELP_SCRIPTS)
def test_script_help_renders(script: str) -> None:
    proc = subprocess.run(
        [sys.executable, script, "--help"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )

    output = f"{proc.stdout}\n{proc.stderr}"
    assert proc.returncode == 0, output
    assert "usage:" in output


def test_review_list_replay_entrypoint_imports() -> None:
    # scripts/_bootstrap.py 会 load_dotenv(override=False)：单纯 pop 掉环境变量后，
    # 子进程会从仓库 .env 兜底加载回真实值，无法触发"未配置"快速失败分支。
    # 显式设为空字符串——变量"存在但为空"，load_dotenv 不会覆盖，还原测试意图。
    env = os.environ.copy()
    env["FEISHU_WEBHOOK_URL"] = ""
    proc = subprocess.run(
        [sys.executable, "scripts/review_list_replay.py"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )

    output = f"{proc.stdout}\n{proc.stderr}"
    assert proc.returncode == 2, output
    assert "FEISHU_WEBHOOK_URL 未配置" in output
    assert "ModuleNotFoundError" not in output
