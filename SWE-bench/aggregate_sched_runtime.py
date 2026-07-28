#!/usr/bin/env python3
import argparse
import json
import re
import subprocess
from collections import defaultdict
from pathlib import Path


CPU_PATTERN = re.compile(r"\[(\d+)\]")
COMM_PATTERN = re.compile(r"comm=(.*?) pid=")
RUNTIME_PATTERN = re.compile(r"runtime=(\d+) \[ns\]")


def write_tsv(path: Path, runtime_ns: dict[str, int]) -> None:
    total = sum(runtime_ns.values())
    lines = ["comm\truntime_ms\tpercent"]
    for comm, value in sorted(runtime_ns.items(), key=lambda item: item[1], reverse=True):
        percent = 100.0 * value / total if total else 0.0
        lines.append(f"{comm}\t{value / 1e6:.6f}\t{percent:.6f}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Aggregate sched_stat_runtime by comm for all recorded CPUs and one focus CPU"
    )
    parser.add_argument("perf_data", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--focus-cpu", type=int, default=0)
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    all_runtime: dict[str, int] = defaultdict(int)
    focus_runtime: dict[str, int] = defaultdict(int)

    process = subprocess.Popen(
        [
            "perf",
            "script",
            "-i",
            str(args.perf_data),
            "-F",
            "comm,cpu,event,trace",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert process.stdout is not None
    for line in process.stdout:
        if "sched:sched_stat_runtime:" not in line:
            continue
        cpu_match = CPU_PATTERN.search(line)
        comm_match = COMM_PATTERN.search(line)
        runtime_match = RUNTIME_PATTERN.search(line)
        if not cpu_match or not comm_match or not runtime_match:
            continue
        cpu = int(cpu_match.group(1))
        comm = comm_match.group(1)
        runtime = int(runtime_match.group(1))
        all_runtime[comm] += runtime
        if cpu == args.focus_cpu:
            focus_runtime[comm] += runtime

    stderr = process.communicate()[1]
    if process.returncode != 0:
        raise SystemExit(f"perf script failed ({process.returncode}): {stderr[-2000:]}")

    write_tsv(args.output_dir / "sched_runtime_all.tsv", all_runtime)
    write_tsv(args.output_dir / f"sched_runtime_cpu{args.focus_cpu}.tsv", focus_runtime)
    summary = {
        "perf_data": str(args.perf_data.resolve()),
        "focus_cpu": args.focus_cpu,
        "all_runtime_ms": sum(all_runtime.values()) / 1e6,
        "focus_runtime_ms": sum(focus_runtime.values()) / 1e6,
        "all_top": sorted(all_runtime.items(), key=lambda item: item[1], reverse=True)[:20],
        "focus_top": sorted(focus_runtime.items(), key=lambda item: item[1], reverse=True)[:20],
    }
    (args.output_dir / "sched_runtime_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
