# PyPI Patch 自动发布

仓库通过 `.github/workflows/pypi_patch_release.yml` 发布 `youngcan-wyckoff-analysis`。`main` 分支的 `CI`
成功后，发布流水线读取 PyPI 当前最新版本，与 `pyproject.toml` 中的版本取较新者并自动递增 patch，随后重新执行
Python 质量门和全量测试、构建 wheel/sdist、校验包元数据并发布。

版本改动只存在于 GitHub Actions 的构建工作区，不会由机器人回写仓库，因此不会产生自动提交循环。流水线使用
`pypa/gh-action-pypi-publish` 的 Trusted Publishing，不需要保存长期 `PYPI_TOKEN`。`workflow_dispatch` 可用于
CI 已通过但发布需要补跑的情况，同样会从 PyPI 最新版本继续递增 patch。

## 一次性配置

1. 在 GitHub 仓库创建名为 `pypi` 的 Environment。
2. 在 PyPI 项目 `youngcan-wyckoff-analysis` 的 Publishing 设置中新增 GitHub Trusted Publisher：
   - Owner: `YoungCan-Wang`
   - Repository: `WyckoffTradingAgent`
   - Workflow: `pypi_patch_release.yml`
   - Environment: `pypi`
3. 将 GitHub Actions repository variable `PYPI_PUBLISH_ENABLED` 改为 `true`。默认保持 `false`，避免 PyPI
   绑定完成前产生失败发布。
4. 不要新增 `PYPI_TOKEN`；发布 job 只申请 `id-token: write`，由 PyPI 签发短时凭证。

发布使用顶层 concurrency 串行执行，避免相邻两次 CI 同时计算出相同 patch 版本。若 PyPI 发布失败，修复配置后从
Actions 手动重跑整个 workflow；不要只重跑 publish job，因为旧 artifact 的版本可能已经被占用。
