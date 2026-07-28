#!/usr/bin/env python3
"""Classify Python-related sandbox tool actions recorded in SWE trajectories."""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


TEST_RE = re.compile(
    r"(^|[\s;&|/])(?:py\.test|pytest|tox|nosetests|runtests(?:\.py)?)(?=$|[\s;&|])"
    r"|python(?:3(?:\.\d+)?)?\s+-m\s+(?:pytest|unittest)",
    re.IGNORECASE,
)
PACKAGE_RE = re.compile(
    r"(^|[\s;&|/])(?:pip3?|conda|mamba|poetry)(?=$|[\s;&|])"
    r"|python(?:3(?:\.\d+)?)?\s+-m\s+pip"
    r"|setup\.py\s+(?:install|develop|build)",
    re.IGNORECASE,
)
PYTHON_RE = re.compile(r"(^|[\s;&|/])python(?:3(?:\.\d+)?)?(?=$|[\s;&|])", re.IGNORECASE)
PYTHON_INLINE_RE = re.compile(
    r"(^|[\s;&|/])python(?:3(?:\.\d+)?)?\s+(?:-c\b|<<)",
    re.IGNORECASE,
)
PYTHON_SCRIPT_RE = re.compile(
    r"(^|[\s;&|/])python(?:3(?:\.\d+)?)?\s+([^\s;&|]+\.py)(?=$|[\s;&|])",
    re.IGNORECASE,
)
PYTHON_CLI_RE = re.compile(
    r"(?:^|[;&|])\s*(?:cd\s+\S+\s*&&\s*)?"
    r"(?:coverage|django-admin|flake8|isort|mypy|pylint|sphinx-build|black)"
    r"(?=$|[\s;&|])",
    re.IGNORECASE,
)
EDIT_HINT_RE = re.compile(
    r"(write_text|write_bytes|open\([^)]*,\s*['\"][wax+]|"
    r"\.write\(|replace\(|rename\(|unlink\()",
    re.IGNORECASE,
)


def ratio(value: int, total: int) -> float:
    return 100.0 * value / total if total else 0.0


def classify(command: str) -> str | None:
    if TEST_RE.search(command):
        return "python_test"
    if PACKAGE_RE.search(command):
        return "python_package_or_env"
    if PYTHON_RE.search(command):
        if EDIT_HINT_RE.search(command):
            return "python_edit_helper"
        script = PYTHON_SCRIPT_RE.search(command)
        if script:
            return (
                "python_reproduction_probe"
                if script.group(2).startswith("/tmp/")
                else "python_project_script"
            )
        if PYTHON_INLINE_RE.search(command):
            return "python_reproduction_probe"
        return "python_other"
    if PYTHON_CLI_RE.search(command):
        return "python_backed_cli"
    return None


def source_model(path: Path) -> str:
    parts = {part.lower() for part in path.parts}
    if "flash" in parts:
        return "flash"
    if "pro" in parts:
        return "pro"
    return "unknown"


def trajectory_rows(path: Path) -> list[dict[str, Any]]:
    trajectory = json.loads(path.read_text(encoding="utf-8"))
    instance_id = trajectory.get("instance_id") or path.stem.removesuffix(".traj")
    rows: list[dict[str, Any]] = []
    step = 0
    for message in trajectory.get("messages") or []:
        if message.get("role") != "assistant":
            continue
        for action in (message.get("extra") or {}).get("actions") or []:
            step += 1
            command = str(action.get("command") or "")
            role = classify(command)
            if role is None:
                continue
            rows.append(
                {
                    "model": source_model(path),
                    "instance_id": instance_id,
                    "step": step,
                    "role": role,
                    "command": command,
                    "trajectory": str(path.resolve()),
                }
            )
    return rows


def trajectory_action_count(path: Path) -> int:
    trajectory = json.loads(path.read_text(encoding="utf-8"))
    return sum(
        len((message.get("extra") or {}).get("actions") or [])
        for message in trajectory.get("messages") or []
        if message.get("role") == "assistant"
    )


def render_markdown(
    rows: list[dict[str, Any]],
    trajectory_count: int,
    action_counts: Counter[str],
) -> str:
    by_model: dict[str, Counter[str]] = defaultdict(Counter)
    examples: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        by_model[row["model"]][row["role"]] += 1
        if len(examples[row["role"]]) < 4:
            examples[row["role"]].append(row["command"].replace("\n", " ")[:240])

    roles = sorted({row["role"] for row in rows})
    total_actions = sum(action_counts.values())
    lines = [
        "# SWE Golden Trajectory 中的 Python 角色",
        "",
        f"- Trajectory：`{trajectory_count}`",
        f"- 全部 Sandbox tool actions：`{total_actions}`",
        f"- 可识别的 Python-related tool actions：`{len(rows)}`",
        f"- Python-related action 占比：`{ratio(len(rows), total_actions):.2f}%`",
        f"- Flash：`{sum(by_model['flash'].values())}/{action_counts['flash']}`；"
        f"Pro：`{sum(by_model['pro'].values())}/{action_counts['pro']}`",
        "",
        "| Role | Flash actions | Pro actions | Total |",
        "|---|---:|---:|---:|",
    ]
    for role in roles:
        flash = by_model["flash"][role]
        pro = by_model["pro"][role]
        lines.append(f"| {role} | {flash} | {pro} | {flash + pro} |")

    lines.extend(
        [
            "",
            "## 角色含义",
            "",
            "- `python_test`：pytest、unittest、tox 等测试执行。",
            "- `python_package_or_env`：pip、conda、setup.py 等依赖和环境操作。",
            "- `python_backed_cli`：pylint、sphinx-build、mypy 等 Python CLI。",
            "- `python_edit_helper`：Agent 临时使用 Python 修改文件。",
            "- `python_reproduction_probe`：`python -c`、heredoc 或 `/tmp` 复现探针。",
            "- `python_project_script`：直接运行仓库中的 Python 脚本。",
            "- `python_other`：能够识别为 Python，但不适合归入上述类别。",
            "",
            "## 边界",
            "",
            "- Trajectory 记录的是 Sandbox tool command，不包含 Host Agent 自身的 Python 调用栈。",
            "- 这里统计 action 数量，不是 CPU time；pytest 及其子进程的运行时间需结合 exec/sched trace。",
            "- 没有显式出现 `python` 的 shebang/间接子进程可能被漏记。",
            "",
            "## 示例",
            "",
        ]
    )
    for role in roles:
        lines.append(f"### {role}")
        lines.append("")
        for command in examples[role]:
            lines.append(f"- `{command}`")
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--csv", type=Path)
    parser.add_argument("--json", type=Path)
    parser.add_argument("--markdown", type=Path)
    args = parser.parse_args()

    paths: list[Path] = []
    for source in args.inputs:
        if source.is_dir():
            paths.extend(sorted(source.rglob("*.traj.json")))
        elif source.is_file():
            paths.append(source)
    unique_paths = sorted(set(path.resolve() for path in paths))
    if not unique_paths:
        raise SystemExit("No trajectory files found")

    rows = [row for path in unique_paths for row in trajectory_rows(path)]
    action_counts: Counter[str] = Counter()
    for path in unique_paths:
        action_counts[source_model(path)] += trajectory_action_count(path)
    markdown = render_markdown(rows, len(unique_paths), action_counts)
    if args.csv:
        args.csv.parent.mkdir(parents=True, exist_ok=True)
        with args.csv.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(
                stream,
                fieldnames=("model", "instance_id", "step", "role", "command", "trajectory"),
            )
            writer.writeheader()
            writer.writerows(rows)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps(
                {
                    "format_version": 1,
                    "trajectory_count": len(unique_paths),
                    "action_counts": dict(action_counts),
                    "python_related_action_count": len(rows),
                    "rows": rows,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(markdown, encoding="utf-8")
    print(markdown)


if __name__ == "__main__":
    main()
