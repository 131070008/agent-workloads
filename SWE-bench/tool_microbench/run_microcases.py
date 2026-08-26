#!/usr/bin/env python3
"""Run extracted grep and editor microcases outside Docker."""

from __future__ import annotations

import argparse
import csv
import json
import os
import resource
import shlex
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any


def normalize(text: str, replacements: list[tuple[str, str]]) -> str:
    normalized = text.replace("\r\n", "\n")
    for source, target in replacements:
        normalized = normalized.replace(source, target)
    return normalized.strip()


def editor_arguments(action: str, local_testbed: Path) -> tuple[list[str], Path]:
    tokens = shlex.split(action)
    if len(tokens) < 3 or tokens[0] != "str_replace_editor":
        raise ValueError(f"Invalid editor action: {action}")
    source_path = Path(tokens[2])
    if not str(source_path).startswith("/testbed/"):
        raise ValueError(f"Editor path is outside /testbed: {source_path}")
    target = local_testbed / source_path.relative_to("/testbed")
    tokens[2] = str(target)
    return tokens[1:], target


def prepare_editor_work(bundle: Path, case: dict[str, Any], run_dir: Path) -> tuple[list[str], Path]:
    local_testbed = run_dir / "testbed"
    local_testbed.mkdir(parents=True)
    args, target = editor_arguments(case["source_action"], local_testbed)
    target.parent.mkdir(parents=True, exist_ok=True)
    command = args[0]
    if command != "create":
        source = bundle / "fixtures" / case["instance_id"] / "testbed" / target.relative_to(local_testbed)
        if not source.is_file():
            raise FileNotFoundError(source)
        shutil.copy2(source, target)
    return args, target


def run_case(
    bundle: Path,
    case: dict[str, Any],
    run_dir: Path,
    cpu: str | None,
    python: str,
) -> dict[str, Any]:
    run_dir.mkdir(parents=True)
    environment = os.environ.copy()
    environment["LC_ALL"] = "C"
    replacements: list[tuple[str, str]] = []
    target: Path | None = None

    if case["family"] == "grep":
        if case["strategy"] == "materialized_stdin":
            generated = bundle / case["materialized_file"]
            command = f"{case['standalone_filter']} {shlex.quote(str(generated))}"
        else:
            fixture = bundle / "fixtures" / case["instance_id"] / "testbed"
            command = case["source_action"].replace("/testbed", str(fixture))
            replacements.append((str(fixture), "/testbed"))
        argv = ["bash", "-lc", command]
    else:
        args, target = prepare_editor_work(bundle, case, run_dir)
        tool = bundle / "editor_tool" / "edit_anthropic" / "bin" / "str_replace_editor"
        registry = bundle / "editor_tool" / "registry"
        environment["PYTHONPATH"] = str(registry) + (
            os.pathsep + environment["PYTHONPATH"] if environment.get("PYTHONPATH") else ""
        )
        environment["SWE_AGENT_ENV_FILE"] = str(run_dir / ".swe-agent-env")
        environment["USE_FILEMAP"] = "false"
        environment["USE_LINTER"] = "false"
        environment["MAX_WINDOW_EXPANSION_VIEW"] = "0"
        environment["MAX_WINDOW_EXPANSION_EDIT_CONFIRM"] = "0"
        argv = [python, str(tool), *args]
        replacements.append((str(run_dir / "testbed"), "/testbed"))
        command = shlex.join(argv)

    if cpu:
        argv = ["taskset", "-c", cpu, *argv]

    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    start_ns = time.perf_counter_ns()
    completed = subprocess.run(argv, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=environment)
    elapsed_ns = time.perf_counter_ns() - start_ns
    after = resource.getrusage(resource.RUSAGE_CHILDREN)

    stdout_path = run_dir / "stdout.txt"
    stderr_path = run_dir / "stderr.txt"
    stdout_path.write_text(completed.stdout, encoding="utf-8")
    stderr_path.write_text(completed.stderr, encoding="utf-8")
    (run_dir / "command.txt").write_text(command + "\n", encoding="utf-8")

    expected = normalize(case.get("source_observation", ""), [])
    actual = normalize(completed.stdout, replacements)
    semantic_match = actual == expected
    exit_ok = completed.returncode == 0 or (
        case["family"] == "grep" and completed.returncode == 1 and expected == ""
    )

    result = {
        "case_id": case["id"],
        "family": case["family"],
        "subtype": case["subtype"],
        "instance_id": case["instance_id"],
        "action_index": case["action_index"],
        "exit_code": completed.returncode,
        "exit_ok": exit_ok,
        "wall_ms": elapsed_ns / 1_000_000,
        "user_ms": (after.ru_utime - before.ru_utime) * 1000,
        "system_ms": (after.ru_stime - before.ru_stime) * 1000,
        "max_rss_kb": after.ru_maxrss,
        "source_execution_ms": (case.get("source_execution_time_seconds") or 0) * 1000,
        "semantic_match": semantic_match,
        "stdout_bytes": len(completed.stdout.encode()),
        "stderr_bytes": len(completed.stderr.encode()),
        "run_dir": str(run_dir),
    }
    if target and target.exists():
        result["target_bytes_after"] = target.stat().st_size
    (run_dir / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle-dir", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--case", action="append", default=[], help="Case ID; repeat to select multiple")
    parser.add_argument("--family", choices=("grep", "editor"))
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--cpu", help="taskset CPU list, for example 2 or 0-7")
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()

    bundle = args.bundle_dir.expanduser().resolve()
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    cases = manifest["cases"]
    if args.list:
        for case in cases:
            print(f"{case['id']}\t{case['family']}\t{case['subtype']}\t{case['instance_id']}#{case['action_index']}")
        return
    if args.case:
        wanted = set(args.case)
        cases = [case for case in cases if case["id"] in wanted]
        missing = wanted - {case["id"] for case in cases}
        if missing:
            parser.error(f"Unknown cases: {', '.join(sorted(missing))}")
    if args.family:
        cases = [case for case in cases if case["family"] == args.family]
    if args.repeat < 1:
        parser.error("--repeat must be at least 1")

    output = (
        args.output_dir.expanduser().resolve()
        if args.output_dir
        else bundle / "results" / datetime.now().strftime("%Y%m%d_%H%M%S")
    )
    if output.exists():
        parser.error(f"Output already exists; choose a new directory: {output}")
    output.mkdir(parents=True)

    rows: list[dict[str, Any]] = []
    for repeat in range(1, args.repeat + 1):
        for case in cases:
            run_dir = output / case["id"] / f"run_{repeat:04d}"
            result = run_case(bundle, case, run_dir, args.cpu, args.python)
            result["repeat"] = repeat
            rows.append(result)
            print(
                f"{case['id']} repeat={repeat} exit={result['exit_code']} "
                f"wall={result['wall_ms']:.3f}ms semantic_match={result['semantic_match']}"
            )

    fields = sorted({key for row in rows for key in row})
    with (output / "results.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    (output / "results.json").write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    failures = [row for row in rows if not row["exit_ok"] or not row["semantic_match"]]
    print(f"OUTPUT={output}")
    print(f"RUNS={len(rows)} FAILURES={len(failures)}")
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
