#!/usr/bin/env python3
"""Run a packaged SWE Golden Set with parallel deterministic replay workers."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import random
import subprocess
import threading
import time
from pathlib import Path
from typing import Any


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_summary(path: Path, jobs: list[dict[str, Any]], config: dict[str, Any]) -> None:
    states: dict[str, int] = {}
    for job in jobs:
        state = job.get("state", "unknown")
        states[state] = states.get(state, 0) + 1
    path.write_text(
        json.dumps(
            {
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "config": config,
                "states": states,
                "jobs": jobs,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def run_job(
    job: dict[str, Any],
    args: argparse.Namespace,
    replay_script: Path,
    stop_event: threading.Event,
) -> dict[str, Any]:
    if stop_event.is_set():
        return job | {"state": "cancelled_before_start"}
    instance_id = job["instance_id"]
    output_dir = args.output_dir / "jobs" / f"repeat_{job['repeat']:02d}" / instance_id
    output_dir.mkdir(parents=True, exist_ok=True)
    log_path = output_dir / "replay.log"
    command = [
        str(args.python),
        str(replay_script),
        "--trajectory",
        str(job["trajectory"]),
        "--output-dir",
        str(output_dir),
        "--cpuset",
        args.sandbox_cpuset,
        "--delay-scale",
        str(args.delay_scale),
        "--container-memory",
        args.container_memory,
        "--container-pids-limit",
        str(args.container_pids_limit),
    ]
    if args.validation_mode == "exact":
        command.append("--strict")
    if args.network_none:
        command.append("--network-none")
    if args.cgroup_parent:
        command.extend(["--cgroup-parent", args.cgroup_parent])
    if args.agent_cpuset:
        command = ["taskset", "-c", args.agent_cpuset, *command]

    started = time.time()
    with log_path.open("w", encoding="utf-8", errors="replace") as log:
        completed = subprocess.run(
            command,
            cwd=str(args.repo),
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=args.timeout,
            check=False,
        )
    validation_path = output_dir / "replay_validation.json"
    validation = read_json(validation_path) if validation_path.exists() else {}
    validation_key = "strict_pass" if args.validation_mode == "exact" else "semantic_pass"
    finished = time.time()
    result = job | {
        "state": "passed" if completed.returncode == 0 and validation.get(validation_key) else "failed",
        "returncode": completed.returncode,
        "started_at": started,
        "finished_at": finished,
        "elapsed_seconds": finished - started,
        "output_dir": str(output_dir),
        "log": str(log_path),
        "validation": validation,
    }
    if result["state"] == "failed" and args.fail_fast:
        stop_event.set()
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--golden-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--repo", type=Path, default=Path("/home/higon/cunzhe/agent-workloads"))
    parser.add_argument("--python", type=Path, default=None)
    parser.add_argument("--workers", type=int, default=30)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--delay-scale", type=float, default=0.0)
    parser.add_argument("--agent-cpuset", default="")
    parser.add_argument("--sandbox-cpuset", default="0-7")
    parser.add_argument("--cgroup-parent", default="")
    parser.add_argument("--network-none", action="store_true")
    parser.add_argument("--container-memory", default="16g")
    parser.add_argument("--container-pids-limit", type=int, default=4096)
    parser.add_argument("--stagger-ms", type=float, default=0.0)
    parser.add_argument("--timeout", type=int, default=7200)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--fail-fast", action="store_true")
    parser.add_argument("--validation-mode", choices=("exact", "semantic"), default="exact")
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
    jobs = [
        {
            "instance_id": case["instance_id"],
            "repeat": repeat,
            "trajectory": str(args.golden_dir / case["trajectory_file"]),
            "source_model": case["metrics"]["source_model"],
        }
        for repeat in range(1, args.repeats + 1)
        for case in manifest["cases"]
    ]
    random.Random(args.seed).shuffle(jobs)
    config = {
        "golden_dir": str(args.golden_dir),
        "label": manifest.get("label"),
        "workers": args.workers,
        "repeats": args.repeats,
        "job_count": len(jobs),
        "delay_scale": args.delay_scale,
        "agent_cpuset": args.agent_cpuset,
        "sandbox_cpuset": args.sandbox_cpuset,
        "network_none": args.network_none,
        "container_memory": args.container_memory,
        "container_pids_limit": args.container_pids_limit,
        "stagger_ms": args.stagger_ms,
        "validation_mode": args.validation_mode,
        "started_at": time.time(),
    }
    (args.output_dir / "run_config.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    results: list[dict[str, Any]] = []
    stop_event = threading.Event()
    lock = threading.Lock()

    def submitted_job(job: dict[str, Any]) -> dict[str, Any]:
        if args.stagger_ms:
            time.sleep(job["submission_index"] * args.stagger_ms / 1000.0)
        return run_job(job, args, replay_script, stop_event)

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = []
        for index, job in enumerate(jobs):
            job["submission_index"] = index
            job["submitted_at"] = time.time()
            futures.append(executor.submit(submitted_job, job))
        for future in concurrent.futures.as_completed(futures):
            try:
                result = future.result()
            except subprocess.TimeoutExpired as error:
                result = {"state": "timeout", "error": repr(error)}
                if args.fail_fast:
                    stop_event.set()
            except Exception as error:
                result = {"state": "runner_exception", "error": repr(error)}
                if args.fail_fast:
                    stop_event.set()
            with lock:
                results.append(result)
                write_summary(args.output_dir / "replay_summary.json", results, config)
            print(
                f"DONE {result.get('instance_id')} repeat={result.get('repeat')} "
                f"state={result.get('state')} seconds={result.get('elapsed_seconds')}",
                flush=True,
            )

    config["finished_at"] = time.time()
    config["elapsed_seconds"] = config["finished_at"] - config["started_at"]
    config["jobs_per_second"] = len(results) / config["elapsed_seconds"] if config["elapsed_seconds"] else 0.0
    write_summary(args.output_dir / "replay_summary.json", results, config)
    failed = [result for result in results if result.get("state") != "passed"]
    if failed:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
