#!/usr/bin/env python3
"""Measure steady SWE replay throughput with a fixed-concurrency closed loop."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import math
import os
import random
import subprocess
import threading
import time
from collections import Counter
from pathlib import Path
from typing import Any


def read_json(path: Path, default: Any = None) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def parse_cpuset(value: str) -> set[int]:
    cpus: set[int] = set()
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start, end = (int(item) for item in part.split("-", 1))
            cpus.update(range(start, end + 1))
        else:
            cpus.add(int(part))
    return cpus


def read_cpu_stat(cpus: set[int]) -> dict[int, tuple[int, int]]:
    result: dict[int, tuple[int, int]] = {}
    for line in Path("/proc/stat").read_text(encoding="utf-8").splitlines():
        fields = line.split()
        if not fields or not fields[0].startswith("cpu") or fields[0] == "cpu":
            continue
        cpu = int(fields[0][3:])
        if cpu not in cpus:
            continue
        values = [int(value) for value in fields[1:]]
        total = sum(values)
        idle = values[3] + (values[4] if len(values) > 4 else 0)
        result[cpu] = (total, idle)
    return result


def cpu_utilization(
    before: dict[int, tuple[int, int]], after: dict[int, tuple[int, int]]
) -> dict[str, float]:
    result: dict[str, float] = {}
    for cpu in sorted(before):
        if cpu not in after:
            continue
        total = after[cpu][0] - before[cpu][0]
        idle = after[cpu][1] - before[cpu][1]
        if total > 0:
            result[f"cpu{cpu}"] = 100.0 * (total - idle) / total
    return result


def summarize_latencies(results: list[dict[str, Any]]) -> dict[str, float | None]:
    values = [float(result["elapsed_seconds"]) for result in results]
    return {
        "min": min(values) if values else None,
        "mean": sum(values) / len(values) if values else None,
        "p50": percentile(values, 0.50),
        "p90": percentile(values, 0.90),
        "p99": percentile(values, 0.99),
        "max": max(values) if values else None,
    }


def summarize_latencies_by_case(
    results: list[dict[str, Any]],
) -> dict[str, dict[str, float | int | None]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for result in results:
        grouped.setdefault(result["instance_id"], []).append(result)
    return {
        instance_id: {"count": len(case_results)} | summarize_latencies(case_results)
        for instance_id, case_results in sorted(grouped.items())
    }


def run_case(
    *,
    phase: str,
    sequence: int,
    worker: int,
    case: dict[str, Any],
    phase_dir: Path,
    args: argparse.Namespace,
    replay_script: Path,
    deadline: float,
) -> dict[str, Any]:
    instance_id = case["instance_id"]
    output_dir = phase_dir / "jobs" / f"job_{sequence:06d}_{instance_id}"
    output_dir.mkdir(parents=True, exist_ok=True)
    command = [
        str(args.python),
        str(replay_script),
        "--trajectory",
        str(args.golden_dir / case["trajectory_file"]),
        "--output-dir",
        str(output_dir),
        "--cpuset",
        args.sandbox_cpuset,
        "--delay-scale",
        "0",
        "--container-memory",
        args.container_memory,
        "--container-pids-limit",
        str(args.container_pids_limit),
        "--network-none",
    ]
    if args.cgroup_parent:
        command.extend(["--cgroup-parent", args.cgroup_parent])
    if args.agent_cpuset:
        command = ["taskset", "-c", args.agent_cpuset, *command]

    started_at = time.time()
    started_monotonic = time.monotonic()
    try:
        with (output_dir / "replay.log").open("w", encoding="utf-8", errors="replace") as log:
            completed = subprocess.run(
                command,
                cwd=str(args.repo),
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=args.job_timeout,
                check=False,
            )
        returncode = completed.returncode
        error = None
    except subprocess.TimeoutExpired as exc:
        returncode = 124
        error = repr(exc)
    finished_monotonic = time.monotonic()
    finished_at = time.time()
    validation_path = output_dir / "replay_validation.json"
    validation = read_json(validation_path, {}) or {}
    state = "passed" if returncode == 0 and validation.get("semantic_pass") else "failed"
    return {
        "phase": phase,
        "sequence": sequence,
        "worker": worker,
        "instance_id": instance_id,
        "started_at": started_at,
        "finished_at": finished_at,
        "elapsed_seconds": finished_monotonic - started_monotonic,
        "completed_before_deadline": finished_monotonic <= deadline,
        "state": state,
        "returncode": returncode,
        "error": error,
        "output_dir": str(output_dir),
        "validation": validation,
    }


def write_phase_summary(
    path: Path,
    *,
    phase: str,
    duration: float,
    started_at: float,
    deadline_at: float,
    finished_at: float,
    results: list[dict[str, Any]],
    cpu: dict[str, float],
    workers: int,
) -> dict[str, Any]:
    completed_in_window = [result for result in results if result["completed_before_deadline"]]
    states = Counter(result["state"] for result in results)
    summary = {
        "phase": phase,
        "workers": workers,
        "target_duration_seconds": duration,
        "started_at": started_at,
        "deadline_at": deadline_at,
        "finished_at": finished_at,
        "drain_seconds": max(0.0, finished_at - deadline_at),
        "issued_jobs": len(results),
        "completed_within_window": len(completed_in_window),
        "completed_after_deadline": len(results) - len(completed_in_window),
        "throughput_cases_per_second": len(completed_in_window) / duration if duration else None,
        "issued_jobs_per_second": len(results) / duration if duration else None,
        "states": dict(states),
        "latency_all_seconds": summarize_latencies(results),
        "latency_completed_within_window_seconds": summarize_latencies(completed_in_window),
        "latency_by_case_all_seconds": summarize_latencies_by_case(results),
        "latency_by_case_completed_within_window_seconds": summarize_latencies_by_case(
            completed_in_window
        ),
        "completed_case_mix": dict(Counter(result["instance_id"] for result in completed_in_window)),
        "cpu_utilization_percent": cpu,
        "cpu_utilization_mean_percent": sum(cpu.values()) / len(cpu) if cpu else None,
        "jobs": results,
    }
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def run_phase(
    phase: str,
    duration: float,
    cases: list[dict[str, Any]],
    output_dir: Path,
    args: argparse.Namespace,
    replay_script: Path,
    cpus: set[int],
) -> dict[str, Any]:
    phase_dir = output_dir / phase
    phase_dir.mkdir(parents=True, exist_ok=True)
    phase_started_at = time.time()
    deadline_monotonic = time.monotonic() + duration
    deadline_at = phase_started_at + duration
    cpu_before = read_cpu_stat(cpus)
    dispatch_lock = threading.Lock()
    results_lock = threading.Lock()
    results: list[dict[str, Any]] = []
    next_sequence = 0

    def worker_loop(worker: int) -> None:
        nonlocal next_sequence
        while True:
            with dispatch_lock:
                if time.monotonic() >= deadline_monotonic:
                    return
                sequence = next_sequence
                next_sequence += 1
            result = run_case(
                phase=phase,
                sequence=sequence,
                worker=worker,
                case=cases[sequence % len(cases)],
                phase_dir=phase_dir,
                args=args,
                replay_script=replay_script,
                deadline=deadline_monotonic,
            )
            with results_lock:
                results.append(result)
                print(
                    f"{phase} finish seq={sequence} worker={worker} "
                    f"case={result['instance_id']} seconds={result['elapsed_seconds']:.3f} "
                    f"in_window={result['completed_before_deadline']}",
                    flush=True,
                )

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [executor.submit(worker_loop, worker) for worker in range(args.workers)]
        remaining = max(0.0, deadline_monotonic - time.monotonic())
        if remaining:
            time.sleep(remaining)
        cpu_after = read_cpu_stat(cpus)
        for future in futures:
            future.result()

    finished_at = time.time()
    cpu = cpu_utilization(cpu_before, cpu_after)
    return write_phase_summary(
        phase_dir / "phase_summary.json",
        phase=phase,
        duration=duration,
        started_at=phase_started_at,
        deadline_at=deadline_at,
        finished_at=finished_at,
        results=sorted(results, key=lambda result: result["sequence"]),
        cpu=cpu,
        workers=args.workers,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--golden-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--repo", type=Path, default=Path("/home/higon/cunzhe/agent-workloads"))
    parser.add_argument("--python", type=Path)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--warmup-seconds", type=float, default=60.0)
    parser.add_argument("--measure-seconds", type=float, default=300.0)
    parser.add_argument("--agent-cpuset", default="0-7")
    parser.add_argument("--sandbox-cpuset", default="0-7")
    parser.add_argument("--container-memory", default="16g")
    parser.add_argument("--container-pids-limit", type=int, default=4096)
    parser.add_argument("--cgroup-parent", default="")
    parser.add_argument("--job-timeout", type=int, default=7200)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    args.golden_dir = args.golden_dir.expanduser().resolve()
    args.output_dir = args.output_dir.expanduser().resolve()
    args.repo = args.repo.expanduser().resolve()
    args.python = Path(
        os.path.abspath(str((args.python or args.repo / ".venv-swe/bin/python").expanduser()))
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    replay_script = args.repo / "SWE-bench/replay_swe_trajectory.py"
    manifest = read_json(args.golden_dir / "manifest.json")
    cases = list(manifest["cases"])
    random.Random(args.seed).shuffle(cases)
    cpus = parse_cpuset(args.agent_cpuset) | parse_cpuset(args.sandbox_cpuset)

    config = {
        "golden_dir": str(args.golden_dir),
        "label": manifest.get("label"),
        "case_count": len(cases),
        "workers": args.workers,
        "warmup_seconds": args.warmup_seconds,
        "measure_seconds": args.measure_seconds,
        "agent_cpuset": args.agent_cpuset,
        "sandbox_cpuset": args.sandbox_cpuset,
        "delay_scale": 0,
        "network_none": True,
        "seed": args.seed,
    }
    (args.output_dir / "run_config.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"OUTPUT_DIR={args.output_dir}", flush=True)
    warmup = run_phase(
        "warmup", args.warmup_seconds, cases, args.output_dir, args, replay_script, cpus
    )
    measurement = run_phase(
        "measurement", args.measure_seconds, cases, args.output_dir, args, replay_script, cpus
    )
    final = {"config": config, "warmup": warmup, "measurement": measurement}
    (args.output_dir / "rate_summary.json").write_text(
        json.dumps(final, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "output_dir": str(args.output_dir),
                "throughput_cases_per_second": measurement["throughput_cases_per_second"],
                "completed_within_window": measurement["completed_within_window"],
                "completed_after_deadline": measurement["completed_after_deadline"],
                "cpu_utilization_mean_percent": measurement["cpu_utilization_mean_percent"],
                "case_latency_all_issued_seconds": measurement["latency_all_seconds"],
                "case_latency_completed_within_window_seconds": measurement[
                    "latency_completed_within_window_seconds"
                ],
                "drain_seconds": measurement["drain_seconds"],
            },
            ensure_ascii=False,
            indent=2,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
