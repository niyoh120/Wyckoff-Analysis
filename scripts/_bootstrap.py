"""Make repo-root imports work when scripts are executed by path."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = str(Path(__file__).resolve().parents[1])
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# 独立脚本入口（非 `wyckoff` CLI）不会自动加载 .env：本地运行 scripts/*.py 时
# TICKFLOW_API_KEY 等密钥只能来自当前 shell，否则会静默 fallback 到限流更严的
# tushare/akshare 且没有任何提示。CI 环境变量已由 Actions Secrets 注入，
# load_dotenv 默认不覆盖已存在的环境变量，不影响生产行为。
from dotenv import load_dotenv

load_dotenv(Path(ROOT) / ".env")
