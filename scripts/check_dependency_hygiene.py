"""Check dependency lockfile and direct-version hygiene.

Default mode is advisory: it fails only for missing lockfiles or unreadable
manifests. Use --strict to fail on range-pinned direct dependencies too.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

DEPENDENCY_SECTIONS = ("dependencies", "devDependencies", "optionalDependencies")
EXACT_NPM_VERSION_RE = re.compile(r"^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)(?:[-+][0-9A-Za-z.-]+)?$")
EXACT_PY_VERSION_RE = re.compile(r"^[A-Za-z0-9_.-]+(?:\[[A-Za-z0-9_,.-]+\])?==[^=<>!~,\s]+$")
NON_REGISTRY_PREFIXES = ("workspace:", "file:", "link:", "portal:")
IGNORED_DIRS = {".git", ".venv", "dist", "node_modules", "__pycache__"}


@dataclass(frozen=True)
class DependencyIssue:
    level: str
    path: str
    message: str


def _rel(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _read_json(path: Path, root: Path) -> tuple[dict, list[DependencyIssue]]:
    try:
        return json.loads(path.read_text(encoding="utf-8")), []
    except (OSError, json.JSONDecodeError) as exc:
        return {}, [DependencyIssue("error", _rel(path, root), f"无法读取 package.json: {exc}")]


def _iter_package_json(root: Path) -> list[Path]:
    web = root / "web"
    start = web if web.exists() else root
    files: list[Path] = []
    for path in start.rglob("package.json"):
        if any(part in IGNORED_DIRS for part in path.parts):
            continue
        files.append(path)
    return sorted(files)


def _is_exact_or_internal_npm(name: str, specifier: str) -> bool:
    if specifier.startswith(NON_REGISTRY_PREFIXES):
        return True
    if specifier.startswith("npm:"):
        alias_target = specifier.removeprefix("npm:")
        at = alias_target.rfind("@")
        specifier = alias_target[at + 1 :] if at > 0 else specifier
    if specifier in {"*", "latest"}:
        return False
    if specifier.startswith(("git+", "github:", "git:", "http:", "https:", "ssh:", "git://")):
        return False
    if name.startswith("@wyckoff/"):
        return True
    return bool(EXACT_NPM_VERSION_RE.match(specifier))


def _check_node(root: Path) -> list[DependencyIssue]:
    issues: list[DependencyIssue] = []
    package_files = _iter_package_json(root)
    if not package_files:
        return issues

    lockfile = root / "web" / "pnpm-lock.yaml"
    if not lockfile.exists():
        issues.append(DependencyIssue("error", "web/pnpm-lock.yaml", "web/package.json 存在但缺少 pnpm lockfile"))
    for path in package_files:
        data, errors = _read_json(path, root)
        issues.extend(errors)
        for section in DEPENDENCY_SECTIONS:
            deps = data.get(section, {})
            if not isinstance(deps, dict):
                continue
            for name, specifier in deps.items():
                spec = str(specifier)
                if not _is_exact_or_internal_npm(str(name), spec):
                    issues.append(
                        DependencyIssue(
                            "warning",
                            _rel(path, root),
                            f"{section}.{name} 使用范围/远端版本 {spec}；建议锁定精确版本并依赖 pnpm-lock.yaml 升级",
                        )
                    )
    if lockfile.exists():
        newest_manifest = max((path.stat().st_mtime for path in package_files), default=0)
        if newest_manifest > lockfile.stat().st_mtime:
            issues.append(
                DependencyIssue(
                    "warning", _rel(lockfile, root), "package.json 比 pnpm-lock.yaml 新，确认已更新 lockfile"
                )
            )
    return issues


def _iter_requirement_lines(path: Path) -> list[tuple[int, str]]:
    lines: list[tuple[int, str]] = []
    if not path.exists():
        return lines
    for idx, raw in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
        line = raw.split("#", 1)[0].strip()
        if line:
            lines.append((idx, line))
    return lines


def _is_exact_requirement(line: str) -> bool:
    if line.startswith(("-", "git+", "http:", "https:", "file:")):
        return True
    return bool(EXACT_PY_VERSION_RE.match(line))


def _iter_pyproject_requirements(path: Path) -> list[tuple[str, str]]:
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    result: list[tuple[str, str]] = []
    section = ""
    collecting = ""
    for raw in lines:
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line.strip("[]")
            collecting = ""
            continue
        if collecting:
            for match in re.finditer(r'"([^"]+)"|\'([^\']+)\'', line):
                result.append((collecting, match.group(1) or match.group(2)))
            if "]" in line:
                collecting = ""
            continue
        if section == "project" and line.startswith("dependencies"):
            collecting = "project.dependencies"
        elif section == "project.optional-dependencies" and "=" in line and "[" in line:
            group = line.split("=", 1)[0].strip()
            collecting = f"project.optional-dependencies.{group}"
        if collecting:
            for match in re.finditer(r'"([^"]+)"|\'([^\']+)\'', line):
                result.append((collecting, match.group(1) or match.group(2)))
            if "]" in line:
                collecting = ""
    return result


def _check_python(root: Path) -> list[DependencyIssue]:
    issues: list[DependencyIssue] = []
    pyproject = root / "pyproject.toml"
    requirements = root / "requirements.txt"
    lockfile = root / "uv.lock"
    if pyproject.exists() and not lockfile.exists():
        issues.append(DependencyIssue("error", "uv.lock", "pyproject.toml 存在但缺少 uv.lock"))
    for section, requirement in _iter_pyproject_requirements(pyproject):
        if not _is_exact_requirement(requirement):
            issues.append(
                DependencyIssue(
                    "warning",
                    "pyproject.toml",
                    f"{section}: {requirement} 不是精确 pin；建议保留 uv.lock 并定期审计升级",
                )
            )
    if requirements.exists():
        for lineno, line in _iter_requirement_lines(requirements):
            if not _is_exact_requirement(line):
                issues.append(
                    DependencyIssue(
                        "warning",
                        f"requirements.txt:{lineno}",
                        f"{line} 不是精确 pin；建议把范围升级交给 lockfile/机器人而不是运行时解析",
                    )
                )
    if lockfile.exists():
        manifests = [path for path in (pyproject, requirements) if path.exists()]
        newest_manifest = max((path.stat().st_mtime for path in manifests), default=0)
        if newest_manifest > lockfile.stat().st_mtime:
            issues.append(DependencyIssue("warning", "uv.lock", "Python 依赖声明比 uv.lock 新，确认已运行 uv lock"))
    return issues


def check_project(root: Path) -> list[DependencyIssue]:
    root = root.resolve()
    return _check_python(root) + _check_node(root)


def _print_issue_list(issues: list[DependencyIssue], *, verbose: bool) -> None:
    shown = issues if verbose else issues[:25]
    for issue in shown:
        print(f"  - {issue.path}: {issue.message}")
    hidden = len(issues) - len(shown)
    if hidden > 0:
        print(f"  ... 还有 {hidden} 条，使用 --verbose 查看全部")


def _print_report(issues: list[DependencyIssue], *, strict: bool, verbose: bool = False) -> None:
    errors = [issue for issue in issues if issue.level == "error"]
    warnings = [issue for issue in issues if issue.level == "warning"]
    if not issues:
        print("Dependency hygiene: PASS")
        return
    print("Dependency hygiene report")
    if errors:
        print("\nErrors:")
        _print_issue_list(errors, verbose=True)
    if warnings:
        print(f"\nWarnings ({len(warnings)}):")
        _print_issue_list(warnings, verbose=verbose)
    if warnings and not strict:
        print("\n默认模式只阻断 error；使用 --strict 可让 warning 也阻断 CI。")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check dependency hygiene for Wyckoff-Analysis")
    parser.add_argument("--root", default=".", help="项目根目录")
    parser.add_argument("--strict", action="store_true", help="warning 也返回非零")
    parser.add_argument("--verbose", action="store_true", help="显示全部 warning")
    args = parser.parse_args(argv)

    issues = check_project(Path(args.root))
    _print_report(issues, strict=args.strict, verbose=args.verbose)
    has_errors = any(issue.level == "error" for issue in issues)
    has_warnings = any(issue.level == "warning" for issue in issues)
    if has_errors or (args.strict and has_warnings):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
