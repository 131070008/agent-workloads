#!/usr/bin/env python3
"""Record selected SWE-bench trajectories with bounded parallel Agent workers."""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import json
import os
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import Any


QUOTA_PATTERNS = (
    "insufficient_quota",
    "insufficient balance",
    "payment required",
    "credits exhausted",
    "tokens exhausted",
    "invalid api key",
    "authentication",
    "unauthorized",
    "http 401",
    "missing credentials",
    "余额不足",
    "额度不足",
    "额度已用完",
)


def iso_time() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def read_cases(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream, delimiter="\t"))


def find_trajectory(root: Path, instance_id: str) -> Path | None:
    candidates = list(root.glob(f"**/{instance_id}.traj.json"))
    terminal = []
    for path in candidates:
        try:
            info = json.loads(path.read_text(encoding="utf-8")).get("info") or {}
        except Exception:
            continue
        if info.get("exit_status"):
            terminal.append(path)
    return max(terminal, key=lambda path: path.stat().st_mtime) if terminal else None


def trajectory_summary(path: Path) -> dict[str, Any]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    info = obj.get("info") or {}
    messages = obj.get("messages") or []
    return {
        "path": str(path),
        "model": (info.get("config") or {}).get("model", {}).get("model_name"),
        "exit_status": info.get("exit_status"),
        "api_calls": (info.get("model_stats") or {}).get("api_calls"),
        "action_count": sum(
            len((message.get("extra") or {}).get("actions") or [])
            for message in messages
            if message.get("role") == "assistant"
        ),
        "patch_chars": len(info.get("submission") or ""),
    }


def quota_hit(text: str) -> bool:
    lower = text.lower()
    return any(pattern in lower for pattern in QUOTA_PATTERNS)


def terminate_process_group(process: subprocess.Popen[str]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def run_case(
    row: dict[str, str],
    index: int,
    args: argparse.Namespace,
    stop_event: threading.Event,
) -> dict[str, Any]:
    instance_id = row["instance_id"]
    case_dir = args.output_dir / "cases" / instance_id
    agent_dir = case_dir / "agent"
    log_path = case_dir / "agent.log"
    case_dir.mkdir(parents=True, exist_ok=True)
    started = time.time()
    status: dict[str, Any] = {
        "instance_id": instance_id,
        "repo": row.get("repo"),
        "started_at": started,
        "started_at_iso": iso_time(),
        "state": "starting",
    }
    if stop_event.is_set():
        return status | {"state": "cancelled_before_start"}

    env = os.environ.copy()
    env.update(
        {
            "SWE_INSTANCE_ID": instance_id,
            "SWE_OUTPUT_DIR": str(agent_dir),
            "SWE_STEP_LIMIT": str(args.step_limit),
            "SWE_AGENT_CORE": str(args.agent_core_start + index % args.workers),
            "SWE_CONTAINER_CPUSET": args.container_cpuset,
            "SWE_MAX_TOKENS": str(args.max_tokens),
            "SWE_CONTAINER_MEMORY": args.container_memory,
            "SWE_CONTAINER_MEMORY_SWAP": args.container_memory,
            "SWE_CONTAINER_PIDS_LIMIT": str(args.container_pids_limit),
            "SWE_LLM_TIMEOUT_SECONDS": str(args.llm_timeout),
            "SWE_MODEL_CLASS": args.model_class,
        }
    )
    command = [str(args.runner)]
    with log_path.open("w", encoding="utf-8", errors="replace") as log:
        log.write(f"START {started} {iso_time()}\n")
        log.write(f"INSTANCE {instance_id}\n")
        log.write(f"AGENT_CORE {env['SWE_AGENT_CORE']}\n")
        log.write(f"CONTAINER_CPUSET {env['SWE_CONTAINER_CPUSET']}\n")
        log.flush()
        process = subprocess.Popen(
            command,
            cwd=str(args.repo),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            start_new_session=True,
            bufsize=1,
        )
        quota_line = ""
        try:
            assert process.stdout is not None
            while process.poll() is None:
                line = process.stdout.readline()
                if line:
                    log.write(line)
                    log.flush()
                    if quota_hit(line):
                        quota_line = line.strip()
                        stop_event.set()
                        terminate_process_group(process)
                        break
                if stop_event.is_set() and not quota_line:
                    terminate_process_group(process)
                    break
                if time.time() - started > args.timeout:
                    terminate_process_group(process)
                    status["timed_out"] = True
                    break
            rest = process.stdout.read()
            if rest:
                log.write(rest)
                if quota_hit(rest):
                    quota_line = rest[-1000:]
                    stop_event.set()
        finally:
            returncode = process.wait()

    trajectory = find_trajectory(agent_dir, instance_id)
    elapsed = time.time() - started
    status.update(
        {
            "finished_at": time.time(),
            "elapsed_seconds": elapsed,
            "returncode": returncode,
            "log": str(log_path),
            "state": "quota_stopped" if quota_line else "recorded" if trajectory else "failed",
            "quota_reason": quota_line,
        }
    )
    if trajectory:
        status["trajectory"] = trajectory_summary(trajectory)
    (case_dir / "record_status.json").write_text(
        json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return status


def write_summary(output_dir: Path, statuses: list[dict[str, Any]], model: str) -> None:
    data = {
        "updated_at": iso_time(),
        "model": model,
        "total": len(statuses),
        "states": {},
        "cases": statuses,
    }
    for status in statuses:
        state = status.get("state", "unknown")
        data["states"][state] = data["states"].get(state, 0) + 1
    (output_dir / "record_summary.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selected-tsv", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--existing-root", type=Path, action="append", default=[])
    parser.add_argument("--repo", type=Path, default=Path("/home/higon/cunzhe/agent-workloads"))
    parser.add_argument("--runner", type=Path, default=None)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--agent-core-start", type=int, default=8)
    parser.add_argument("--container-cpuset", default="0-7")
    parser.add_argument("--container-memory", default="16g")
    parser.add_argument("--container-pids-limit", type=int, default=4096)
    parser.add_argument("--step-limit", type=int, default=80)
    parser.add_argument("--max-tokens", type=int, default=8192)
    parser.add_argument("--timeout", type=int, default=7200)
    parser.add_argument("--llm-timeout", type=int, default=180)
    parser.add_argument("--model-class", default="litellm_textbased")
    args = parser.parse_args()
    args.selected_tsv = args.selected_tsv.expanduser().resolve()
    args.output_dir = args.output_dir.expanduser().resolve()
    args.repo = args.repo.expanduser().resolve()
    args.runner = (args.runner or args.repo / "SWE-bench/run_swe_lite_official_case.sh").resolve()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is not exported; source the model env before recording")
    model = os.environ.get("SWE_MODEL", "")
    if not model:
        raise SystemExit("SWE_MODEL is not exported")

    rows = read_cases(args.selected_tsv)
    statuses: list[dict[str, Any]] = []
    pending: list[tuple[int, dict[str, str]]] = []
    for index, row in enumerate(rows):
        existing = next(
            (path for root in args.existing_root if (path := find_trajectory(root.expanduser().resolve(), row["instance_id"]))),
            None,
        )
        if existing:
            statuses.append(
                {
                    "instance_id": row["instance_id"],
                    "repo": row.get("repo"),
                    "state": "existing",
                    "trajectory": trajectory_summary(existing),
                }
            )
        else:
            pending.append((index, row))

    print(f"MODEL {model}", flush=True)
    print(f"CASES total={len(rows)} existing={len(statuses)} pending={len(pending)} workers={args.workers}", flush=True)
    stop_event = threading.Event()
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(run_case, row, index, args, stop_event): row["instance_id"]
            for index, row in pending
        }
        for future in concurrent.futures.as_completed(futures):
            instance_id = futures[future]
            try:
                status = future.result()
            except Exception as error:
                status = {"instance_id": instance_id, "state": "runner_exception", "error": repr(error)}
                stop_event.set()
            statuses.append(status)
            print(
                f"DONE {instance_id} state={status.get('state')} "
                f"seconds={status.get('elapsed_seconds')} actions={(status.get('trajectory') or {}).get('action_count')}",
                flush=True,
            )
            write_summary(args.output_dir, statuses, model)

    statuses.sort(key=lambda item: item["instance_id"])
    write_summary(args.output_dir, statuses, model)
    if stop_event.is_set():
        sentinel = args.output_dir / "QUOTA_OR_BATCH_STOP_README.log"
        sentinel.write_text(
            "Recording stopped after a quota/authentication error or worker exception.\n"
            "Inspect record_summary.json and per-case agent.log before resuming.\n",
            encoding="utf-8",
        )
        raise SystemExit(86)


if __name__ == "__main__":
    main()
