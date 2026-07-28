#!/usr/bin/env python3
"""Run complete SWE Golden trajectories with every ToolCall instrumented by Intel SDE."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import queue
import subprocess
import time
from pathlib import Path
from typing import Any


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_cpu_list(value: str) -> list[str]:
    cpus: list[str] = []
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start, end = (int(item) for item in part.split("-", 1))
            cpus.extend(str(cpu) for cpu in range(start, end + 1))
        else:
            cpus.append(str(int(part)))
    if not cpus:
        raise ValueError("CPU list is empty")
    return cpus


def parse_golden(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("--golden must be LABEL=PATH")
    label, raw_path = value.split("=", 1)
    if not label:
        raise argparse.ArgumentTypeError("Golden label is empty")
    return label, Path(raw_path).expanduser().resolve()


def trajectory_action_count(path: Path) -> int:
    trajectory = read_json(path)
    return sum(
        len((message.get("extra") or {}).get("actions") or [])
        for message in trajectory.get("messages", [])
        if message.get("role") == "assistant"
    )


def next_attempt_dir(case_root: Path) -> Path:
    existing = sorted(
        int(path.name.split("_", 1)[1])
        for path in case_root.glob("attempt_*")
        if path.name.split("_", 1)[-1].isdigit()
    )
    number = existing[-1] + 1 if existing else 1
    return case_root / f"attempt_{number:02d}"


def cleanup_attempt_container(replay_dir: Path) -> dict[str, Any]:
    lifecycle_path = replay_dir / "sandbox_lifecycle.json"
    if not lifecycle_path.exists():
        return {"container_id": None, "cleanup_attempted": False}
    lifecycle = read_json(lifecycle_path)
    container_id = lifecycle.get("container_id")
    if not container_id:
        return {"container_id": None, "cleanup_attempted": False}
    inspected = subprocess.run(
        ["docker", "inspect", container_id],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if inspected.returncode != 0:
        return {
            "container_id": container_id,
            "cleanup_attempted": False,
            "container_absent": True,
        }
    removed = subprocess.run(
        ["docker", "rm", "-f", container_id],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=120,
        check=False,
    )
    return {
        "container_id": container_id,
        "cleanup_attempted": True,
        "container_absent": removed.returncode == 0,
        "docker_rm_returncode": removed.returncode,
    }


def run_case(
    job: dict[str, Any],
    args: argparse.Namespace,
    cpu_pool: queue.Queue[str],
) -> dict[str, Any]:
    label = job["label"]
    instance_id = job["instance_id"]
    case_root = args.output_dir / "cases" / label / instance_id
    complete_path = case_root / "complete.json"
    if args.resume and complete_path.exists():
        complete = read_json(complete_path)
        return complete | {"state": "skipped_complete"}

    attempt_dir = next_attempt_dir(case_root)
    replay_dir = attempt_dir / "replay"
    sde_dir = attempt_dir / "sde_mix"
    attempt_dir.mkdir(parents=True, exist_ok=True)
    cpu = cpu_pool.get()
    started = time.time()
    command = [
        "taskset",
        "-c",
        cpu,
        str(args.python),
        str(args.replay_script),
        "--trajectory",
        str(job["trajectory"]),
        "--output-dir",
        str(replay_dir),
        "--cpuset",
        cpu,
        "--delay-scale",
        "0",
        "--network-none",
        "--container-memory",
        args.container_memory,
        "--container-pids-limit",
        str(args.container_pids_limit),
        "--sde",
        "--sde-home",
        str(args.sde_home),
        "--sde-output-dir",
        str(sde_dir),
        "--sde-action-timeout",
        str(args.action_timeout),
    ]
    if args.max_actions:
        command.extend(["--sde-max-actions", str(args.max_actions)])

    metadata = {
        "format_version": 1,
        **job,
        "cpu": cpu,
        "attempt_dir": str(attempt_dir),
        "command": command,
        "started_at": started,
        "state": "running",
    }
    write_json(attempt_dir / "attempt.json", metadata)
    timed_out = False
    returncode = None
    cleanup = {}
    try:
        with (attempt_dir / "replay.log").open("w", encoding="utf-8", errors="replace") as log:
            completed = subprocess.run(
                command,
                cwd=str(args.repo),
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=args.case_timeout,
                check=False,
            )
        returncode = completed.returncode
    except subprocess.TimeoutExpired:
        timed_out = True
    finally:
        cleanup = cleanup_attempt_container(replay_dir)
        cpu_pool.put(cpu)

    action_metadata = sorted(sde_dir.glob("action_*/action_metadata.json"))
    mix_files = sorted(sde_dir.glob("action_*/mix*.txt"))
    finished = time.time()
    result = metadata | {
        "finished_at": finished,
        "elapsed_seconds": finished - started,
        "returncode": returncode,
        "timed_out": timed_out,
        "container_cleanup": cleanup,
        "instrumented_action_count": len(action_metadata),
        "mix_file_count": len(mix_files),
        "state": (
            "complete"
            if not timed_out
            and returncode == 0
            and len(action_metadata) == job["expected_action_count"]
            else "incomplete"
        ),
    }
    write_json(attempt_dir / "attempt.json", result)
    if result["state"] == "complete":
        write_json(complete_path, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--golden", action="append", type=parse_golden, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--repo", type=Path, default=Path("/home/higon/cunzhe/agent-workloads"))
    parser.add_argument("--python", type=Path)
    parser.add_argument("--sde-home", type=Path, required=True)
    parser.add_argument("--cpus", default="0-7")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--action-timeout", type=int, default=1800)
    parser.add_argument("--case-timeout", type=int, default=21600)
    parser.add_argument("--container-memory", default="16g")
    parser.add_argument("--container-pids-limit", type=int, default=4096)
    parser.add_argument("--max-actions", type=int, default=0)
    parser.add_argument(
        "--instance",
        action="append",
        default=[],
        help="Run only selected instance_id values; may be repeated",
    )
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()

    args.output_dir = args.output_dir.expanduser().resolve()
    args.repo = args.repo.expanduser().resolve()
    args.python = Path(
        os.path.abspath(str((args.python or args.repo / ".venv-swe/bin/python").expanduser()))
    )
    args.sde_home = args.sde_home.expanduser().resolve()
    args.replay_script = args.repo / "SWE-bench/replay_swe_trajectory.py"
    args.output_dir.mkdir(parents=True, exist_ok=True)
    cpus = parse_cpu_list(args.cpus)
    if args.workers > len(cpus):
        raise SystemExit("workers must not exceed the number of leased CPUs")
    if not args.python.is_file() or not args.replay_script.is_file():
        raise SystemExit("SWE replay Python or script is missing")
    if not (args.sde_home / "sde64").is_file():
        raise SystemExit(f"Intel SDE is missing: {args.sde_home / 'sde64'}")

    jobs: list[dict[str, Any]] = []
    for label, golden_dir in args.golden:
        manifest = read_json(golden_dir / "manifest.json")
        for case in manifest["cases"]:
            if args.instance and case["instance_id"] not in args.instance:
                continue
            trajectory = golden_dir / case["trajectory_file"]
            jobs.append(
                {
                    "label": label,
                    "golden_dir": str(golden_dir),
                    "instance_id": case["instance_id"],
                    "trajectory": str(trajectory),
                    "expected_action_count": trajectory_action_count(trajectory),
                    "source_model": case["metrics"]["source_model"],
                }
            )
    jobs.sort(key=lambda item: (item["label"], item["instance_id"]))
    config = {
        "format_version": 1,
        "started_at": time.time(),
        "hostname": os.uname().nodename,
        "golden": [{"label": label, "path": str(path)} for label, path in args.golden],
        "output_dir": str(args.output_dir),
        "cpus": cpus,
        "workers": args.workers,
        "job_count": len(jobs),
        "expected_action_count": sum(job["expected_action_count"] for job in jobs),
        "action_timeout": args.action_timeout,
        "case_timeout": args.case_timeout,
        "max_actions": args.max_actions,
        "instance_filter": args.instance,
        "resume": args.resume,
        "analysis_container": {
            "network": "none",
            "pid": "host",
            "capabilities": ["SYS_ADMIN", "SYS_PTRACE"],
            "seccomp": "unconfined",
        },
    }
    write_json(args.output_dir / "run_config.json", config)
    cpu_pool: queue.Queue[str] = queue.Queue()
    for cpu in cpus:
        cpu_pool.put(cpu)

    results: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [executor.submit(run_case, job, args, cpu_pool) for job in jobs]
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            results.append(result)
            write_json(
                args.output_dir / "run_status.json",
                {
                    "config": config,
                    "updated_at": time.time(),
                    "states": {
                        state: sum(item["state"] == state for item in results)
                        for state in sorted({item["state"] for item in results})
                    },
                    "results": results,
                },
            )
            print(
                f"{result['state'].upper()} {result['label']} {result['instance_id']} "
                f"actions={result.get('instrumented_action_count')} "
                f"seconds={result.get('elapsed_seconds', 0):.1f}",
                flush=True,
            )

    config["finished_at"] = time.time()
    config["elapsed_seconds"] = config["finished_at"] - config["started_at"]
    write_json(args.output_dir / "run_config.json", config)
    summary_script = args.repo / "SWE-bench/summarize_sde_golden_set.py"
    subprocess.run(
        [str(args.python), str(summary_script), str(args.output_dir)],
        cwd=str(args.repo),
        check=False,
    )
    incomplete = [result for result in results if result["state"] == "incomplete"]
    if incomplete:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
