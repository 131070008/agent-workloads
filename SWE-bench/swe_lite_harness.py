#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Local harness for SWE-bench Lite smoke workloads."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[2]
WORKLOAD_DIR = Path(__file__).resolve().parent
DEFAULT_ARROW = WORKLOAD_DIR / "datasets/swe_bench_lite_smoke/raw/swe-bench_lite-test.arrow"
DEFAULT_CASES = WORKLOAD_DIR / "datasets/swe_bench_lite_smoke/cases/smoke_cases.jsonl"
DEFAULT_RESULTS = WORKLOAD_DIR / "results/swe_bench_lite_smoke"
DEFAULT_RUNNER = ROOT / "cpu-centric-agentic-ai/mini-swe-agent/benchmark_latency.py"
DEFAULT_RUNNER_CWD = ROOT / "cpu-centric-agentic-ai/mini-swe-agent"
DEFAULT_PYTHON = ROOT / "cpu-centric-agentic-ai/.venv-swe/bin/python"


def iter_cases(path: Path) -> Iterable[dict]:
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)


def list_cases(path: Path) -> None:
    print(f"cases={path}")
    for rec in iter_cases(path):
        print(
            f"{rec['instance_id']}\t{rec['repo']}\t"
            f"chars={rec['problem_statement_chars']}\t{rec.get('selection_note', '')}"
        )


def build_command(args: argparse.Namespace) -> list[str]:
    return [
        str(args.python_bin),
        str(args.runner),
        "--benchmark-type",
        "swebench",
        "--swebench-arrow",
        str(args.arrow),
        "--swebench-instance",
        args.instance,
        "--base-url",
        args.base_url,
        "--model-path",
        args.model,
        "--api-key",
        args.api_key,
        "--max-instances",
        "1",
        "--max-tokens",
        str(args.max_tokens),
        "--request-timeout",
        str(args.request_timeout),
        "--max-retries",
        str(args.max_retries),
        "--temperature",
        str(args.temperature),
        "--output-dir",
        str(args.output_dir),
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run local SWE-bench Lite smoke cases")
    parser.add_argument("--arrow", type=Path, default=DEFAULT_ARROW)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--instance", default="pallets__flask-4045")
    parser.add_argument("--runner", type=Path, default=DEFAULT_RUNNER)
    parser.add_argument("--runner-cwd", type=Path, default=DEFAULT_RUNNER_CWD)
    parser.add_argument("--python-bin", type=Path, default=DEFAULT_PYTHON)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--base-url", default="http://127.0.0.1:11434")
    parser.add_argument("--model", default="qwen3.6:27b")
    parser.add_argument("--api-key", default="EMPTY")
    parser.add_argument("--max-tokens", type=int, default=512)
    parser.add_argument("--request-timeout", type=int, default=900)
    parser.add_argument("--max-retries", type=int, default=1)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--list-cases", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.list_cases:
        list_cases(args.cases)
        return

    for path in (args.arrow, args.runner, args.python_bin):
        if not path.exists():
            raise SystemExit(f"Missing required path: {path}")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    cmd = build_command(args)

    print("SWE-bench Lite smoke command:")
    print(" ".join(cmd))
    print(f"cwd={args.runner_cwd}")

    if args.dry_run:
        return

    completed = subprocess.run(cmd, cwd=args.runner_cwd)
    sys.exit(completed.returncode)


if __name__ == "__main__":
    main()
