#!/usr/bin/env python3
"""Replay one mini-SWE-agent trajectory without calling an LLM API.

The recorded assistant actions are returned by mini-SWE-agent's deterministic
model. Commands still execute in a fresh SWE-bench Docker container, so the
agent control path, container runtime, tools, and output capture all run again.
"""

from __future__ import annotations

import argparse
import copy
import csv
import gc
import hashlib
import json
import subprocess
import time
from pathlib import Path
from typing import Any

from datasets import Dataset
from minisweagent.run.benchmarks.swebench import process_instance
from minisweagent.run.benchmarks.utils.batch_progress import RunBatchProgressManager


WORKLOAD_DIR = Path(__file__).resolve().parent
DEFAULT_ARROW = WORKLOAD_DIR / "datasets/swe_bench_lite_smoke/raw/swe-bench_lite-test.arrow"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_json(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256_text(payload)


def replay_outputs(trajectory: dict[str, Any]) -> list[dict[str, Any]]:
    """Return compact action messages and any required recorded terminal state."""
    outputs: list[dict[str, Any]] = []
    for message in trajectory.get("messages", []):
        if message.get("role") != "assistant":
            continue
        actions = (message.get("extra") or {}).get("actions") or []
        if not actions:
            continue
        outputs.append(
            {
                "role": "assistant",
                "content": message.get("content", ""),
                "extra": {
                    "actions": copy.deepcopy(actions),
                    "cost": 0.0,
                },
            }
        )
    if not outputs:
        raise ValueError("trajectory contains no replayable assistant actions")
    info = trajectory.get("info") or {}
    exit_status = info.get("exit_status")
    if exit_status not in {"Submitted", "LimitsExceeded"}:
        outputs.append(
            {
                "role": "exit",
                "content": exit_status or "RecordedExit",
                "extra": {
                    "exit_status": exit_status,
                    "submission": info.get("submission") or "",
                    "cost": 0.0,
                },
            }
        )
    return outputs


def action_commands(trajectory: dict[str, Any]) -> list[str]:
    commands: list[str] = []
    for message in trajectory.get("messages", []):
        if message.get("role") != "assistant":
            continue
        for action in (message.get("extra") or {}).get("actions") or []:
            commands.append(str(action.get("command", "")))
    return commands


def action_returncodes(trajectory: dict[str, Any]) -> list[int | None]:
    return [
        (message.get("extra") or {}).get("returncode")
        for message in trajectory.get("messages", [])
        if message.get("role") == "user"
        and isinstance(message.get("extra"), dict)
        and "returncode" in message["extra"]
    ]


def action_arrival_delays(trajectory: dict[str, Any]) -> list[float]:
    """Measure local gaps from one tool completion to the next model action."""
    messages = trajectory.get("messages", [])
    delays: list[float] = []
    previous_done: float | None = None
    for index, message in enumerate(messages):
        if message.get("role") != "assistant" or not (message.get("extra") or {}).get("actions"):
            continue
        response_done = (message.get("extra") or {}).get("timestamp")
        if previous_done is None:
            delays.append(0.0)
        elif isinstance(response_done, (int, float)):
            delays.append(max(0.0, response_done - previous_done))
        else:
            delays.append(0.0)
        observation = next(
            (
                candidate
                for candidate in messages[index + 1 :]
                if candidate.get("role") == "user"
                and isinstance(candidate.get("extra"), dict)
                and "timestamp" in candidate["extra"]
            ),
            None,
        )
        if observation and isinstance(observation["extra"].get("timestamp"), (int, float)):
            previous_done = observation["extra"]["timestamp"]
    return delays


def command_category(commands: list[str]) -> str:
    text = "\n".join(commands).lower()
    if any(token in text for token in ("apply_patch", "sed -i", "perl -pi", "cat >", "cat <<", "tee ")):
        return "edit"
    if any(token in text for token in ("pip install", "apt-get", "apt install", "conda install")):
        return "install"
    if any(token in text for token in ("pytest", "unittest", "tox ", "runtests")):
        return "test"
    if any(token in text for token in ("rg ", "grep ", "find ", "cat ", "sed -n", "head ", "tail ", "ls ")):
        return "inspect"
    if text.lstrip().startswith("git "):
        return "git"
    if any(token in text for token in ("python ", "python3 ", "python -m", "python3 -m")):
        return "python"
    return "shell"


def build_step_timeline(
    trajectory: dict[str, Any],
    process_started_at: float,
    process_finished_at: float,
    delay_scale: float,
) -> dict[str, Any]:
    messages = trajectory.get("messages") or []
    steps: list[dict[str, Any]] = []
    previous_observation_at: float | None = None

    for message_index, message in enumerate(messages):
        if message.get("role") != "assistant":
            continue
        extra = message.get("extra") or {}
        actions = extra.get("actions") or []
        if not actions:
            continue
        commands = [str(action.get("command", "")) for action in actions]
        action_at = extra.get("timestamp")
        observation = next(
            (
                candidate
                for candidate in messages[message_index + 1 :]
                if candidate.get("role") == "user"
                and isinstance(candidate.get("extra"), dict)
                and "timestamp" in candidate["extra"]
            ),
            None,
        )
        observation_extra = (observation or {}).get("extra") or {}
        observation_at = observation_extra.get("timestamp")
        action_gap = (
            max(0.0, action_at - previous_observation_at)
            if isinstance(action_at, (int, float))
            and isinstance(previous_observation_at, (int, float))
            else None
        )
        tool_wall = (
            max(0.0, observation_at - action_at)
            if isinstance(action_at, (int, float)) and isinstance(observation_at, (int, float))
            else None
        )
        content = str((observation or {}).get("content", ""))
        steps.append(
            {
                "step": len(steps) + 1,
                "category": command_category(commands),
                "commands": commands,
                "action_timestamp": action_at,
                "observation_timestamp": observation_at,
                "action_gap_seconds": action_gap,
                "tool_wall_seconds": tool_wall,
                "returncode": observation_extra.get("returncode"),
                "output_chars": len(content),
                "output_lines": content.count("\n") + bool(content),
            }
        )
        if isinstance(observation_at, (int, float)):
            previous_observation_at = observation_at

    first_action_at = next(
        (step["action_timestamp"] for step in steps if isinstance(step["action_timestamp"], (int, float))),
        None,
    )
    last_observation_at = next(
        (
            step["observation_timestamp"]
            for step in reversed(steps)
            if isinstance(step["observation_timestamp"], (int, float))
        ),
        None,
    )
    return {
        "format_version": 1,
        "delay_scale": delay_scale,
        "process_instance_started_at": process_started_at,
        "process_instance_finished_at": process_finished_at,
        "process_instance_elapsed_seconds": process_finished_at - process_started_at,
        "startup_to_first_action_seconds": (
            max(0.0, first_action_at - process_started_at)
            if isinstance(first_action_at, (int, float))
            else None
        ),
        "last_observation_to_finish_seconds": (
            max(0.0, process_finished_at - last_observation_at)
            if isinstance(last_observation_at, (int, float))
            else None
        ),
        "step_count": len(steps),
        "action_gap_sum_seconds": sum(step["action_gap_seconds"] or 0.0 for step in steps),
        "tool_wall_sum_seconds": sum(step["tool_wall_seconds"] or 0.0 for step in steps),
        "steps": steps,
    }


def write_step_timeline(output_dir: Path, timeline: dict[str, Any]) -> tuple[Path, Path]:
    json_path = output_dir / "step_timeline.json"
    tsv_path = output_dir / "step_timeline.tsv"
    json_path.write_text(json.dumps(timeline, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with tsv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=(
                "step",
                "category",
                "action_gap_seconds",
                "tool_wall_seconds",
                "returncode",
                "output_chars",
                "output_lines",
                "command",
            ),
            delimiter="\t",
        )
        writer.writeheader()
        for step in timeline["steps"]:
            writer.writerow(
                {
                    key: step.get(key)
                    for key in (
                        "step",
                        "category",
                        "action_gap_seconds",
                        "tool_wall_seconds",
                        "returncode",
                        "output_chars",
                        "output_lines",
                    )
                }
                | {"command": " ; ".join(step["commands"]).replace("\n", "\\n")}
            )
    return json_path, tsv_path


def image_metadata(image: str) -> dict[str, str]:
    completed = subprocess.run(
        ["docker", "image", "inspect", image],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        return {"reference": image, "inspect_error": completed.stderr.strip()}
    inspected = json.loads(completed.stdout)[0]
    return {
        "reference": image,
        "image_id": inspected.get("Id", ""),
        "platform": f"{inspected.get('Os', '')}/{inspected.get('Architecture', '')}",
        "repo_digests": ",".join(inspected.get("RepoDigests") or []),
    }


def build_config(
    source: dict[str, Any],
    outputs: list[dict[str, Any]],
    replay_trajectory: Path,
    cpuset: str,
    cgroup_parent: str,
    network_none: bool,
    container_memory: str,
    container_pids_limit: int,
    delay_scale: float,
    telemetry_path: Path,
    sde: bool = False,
    sde_home: Path | None = None,
    sde_output_dir: Path | None = None,
    sde_action_timeout: int = 1800,
    sde_max_actions: int = 0,
) -> dict[str, Any]:
    source_config = copy.deepcopy((source.get("info") or {}).get("config") or {})
    agent = source_config.get("agent") or {}
    environment = source_config.get("environment") or {}

    original_exit = (source.get("info") or {}).get("exit_status")
    agent["step_limit"] = len(outputs) if original_exit == "LimitsExceeded" else len(outputs) + 1
    agent["cost_limit"] = 0.0
    agent["wall_time_limit_seconds"] = 0
    agent["output_path"] = str(replay_trajectory)

    run_args = ["--rm"]
    if cpuset:
        run_args.append(f"--cpuset-cpus={cpuset}")
    if cgroup_parent:
        run_args.append(f"--cgroup-parent={cgroup_parent}")
    if network_none:
        run_args.append("--network=none")
    if container_memory:
        run_args.extend([f"--memory={container_memory}", f"--memory-swap={container_memory}"])
    if container_pids_limit:
        run_args.append(f"--pids-limit={container_pids_limit}")
    if sde:
        if sde_home is None or sde_output_dir is None:
            raise ValueError("SDE mode requires sde_home and sde_output_dir")
        sde_output_dir.mkdir(parents=True, exist_ok=True)
        run_args.extend(
            [
                "--pid=host",
                "--cap-add=SYS_ADMIN",
                "--cap-add=SYS_PTRACE",
                "--security-opt=seccomp=unconfined",
                f"--volume={sde_home}:/opt/intel-sde:ro",
                f"--volume={sde_output_dir}:/sde-output",
            ]
        )
    environment["run_args"] = run_args
    environment["environment_class"] = (
        "swe_replay_environment.SDEMeasuredDockerEnvironment"
        if sde
        else "swe_replay_environment.MeasuredDockerEnvironment"
    )
    environment["telemetry_path"] = str(telemetry_path)
    if sde:
        environment.update(
            {
                "sde_output_root": str(sde_output_dir),
                "sde_container_home": "/opt/intel-sde",
                "sde_action_timeout": sde_action_timeout,
                "sde_max_actions": sde_max_actions,
            }
        )

    return {
        "agent": agent,
        "environment": environment,
        "model": {
            "model_name": "deterministic",
            "model_class": "swe_replay_model.TimedDeterministicModel",
            "outputs": outputs,
            "cost_per_call": 0.0,
            "replay_delays": action_arrival_delays(source),
            "delay_scale": delay_scale,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trajectory", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--arrow", type=Path, default=DEFAULT_ARROW)
    parser.add_argument("--cpuset", default="")
    parser.add_argument("--cgroup-parent", default="")
    parser.add_argument("--network-none", action="store_true")
    parser.add_argument("--container-memory", default="16g")
    parser.add_argument("--container-pids-limit", type=int, default=4096)
    parser.add_argument("--delay-scale", type=float, default=0.0)
    parser.add_argument("--sde", action="store_true", help="Run each ToolCall under Intel SDE")
    parser.add_argument(
        "--sde-home",
        type=Path,
        default=Path("/home/higon/sde-external-9.48.0-2024-11-25-lin"),
    )
    parser.add_argument("--sde-output-dir", type=Path)
    parser.add_argument("--sde-action-timeout", type=int, default=1800)
    parser.add_argument(
        "--sde-max-actions",
        type=int,
        default=0,
        help="Instrument only the first N actions; zero instruments all actions",
    )
    parser.add_argument("--strict", action="store_true", help="Exit nonzero unless commands, return codes, exit, and patch match")
    args = parser.parse_args()

    source_path = args.trajectory.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    source = read_json(source_path)
    instance_id = source.get("instance_id")
    if not instance_id:
        raise SystemExit("trajectory has no instance_id")

    dataset = Dataset.from_file(str(args.arrow.expanduser().resolve()))
    instance = next((dict(row) for row in dataset if row["instance_id"] == instance_id), None)
    if instance is None:
        raise SystemExit(f"SWE-bench Lite instance not found: {instance_id}")

    outputs = replay_outputs(source)
    sde_home = args.sde_home.expanduser().resolve() if args.sde else None
    sde_output_dir = (
        (args.sde_output_dir or output_dir / "sde_mix").expanduser().resolve()
        if args.sde
        else None
    )
    if args.sde and not (sde_home / "sde64").is_file():
        raise SystemExit(f"Intel SDE not found: {sde_home / 'sde64'}")
    replay_path = output_dir / instance_id / f"{instance_id}.traj.json"
    lifecycle_path = output_dir / "sandbox_lifecycle.json"
    replay_path.parent.mkdir(parents=True, exist_ok=True)
    config = build_config(
        source,
        outputs,
        replay_path,
        args.cpuset,
        args.cgroup_parent,
        args.network_none,
        args.container_memory,
        args.container_pids_limit,
        args.delay_scale,
        lifecycle_path,
        args.sde,
        sde_home,
        sde_output_dir,
        args.sde_action_timeout,
        args.sde_max_actions,
    )

    image = (source.get("info") or {}).get("config", {}).get("environment", {}).get("image", "")
    started = time.time()
    progress = RunBatchProgressManager(1, output_dir / f"exit_statuses_{started}.yaml")
    process_instance(instance, output_dir, config, progress)
    gc.collect()
    finished = time.time()
    elapsed = finished - started

    if not replay_path.exists():
        raise SystemExit(f"replay trajectory was not produced: {replay_path}")
    replay = read_json(replay_path)
    timeline = build_step_timeline(replay, started, finished, args.delay_scale)
    lifecycle = read_json(lifecycle_path) if lifecycle_path.exists() else {}
    first_action_at = next(
        (
            step.get("action_timestamp")
            for step in timeline.get("steps") or []
            if isinstance(step.get("action_timestamp"), (int, float))
        ),
        None,
    )
    last_observation_at = next(
        (
            step.get("observation_timestamp")
            for step in reversed(timeline.get("steps") or [])
            if isinstance(step.get("observation_timestamp"), (int, float))
        ),
        None,
    )
    container_running_at = lifecycle.get("container_running_at")
    cleanup_requested_at = lifecycle.get("cleanup_requested_at")
    container_removed_at = lifecycle.get("container_removed_at")
    timeline.update(
        {
            "sandbox_lifecycle": lifecycle,
            "sandbox_e2e_seconds": lifecycle.get("sandbox_e2e_seconds"),
            "container_start_seconds": lifecycle.get("container_start_seconds"),
            "agent_init_after_container_seconds": (
                max(0.0, first_action_at - container_running_at)
                if isinstance(first_action_at, (int, float))
                and isinstance(container_running_at, (int, float))
                else None
            ),
            "result_capture_seconds": (
                max(0.0, cleanup_requested_at - last_observation_at)
                if isinstance(cleanup_requested_at, (int, float))
                and isinstance(last_observation_at, (int, float))
                else None
            ),
            "container_teardown_seconds": lifecycle.get("container_teardown_seconds"),
            "post_teardown_seconds": (
                max(0.0, finished - container_removed_at)
                if isinstance(container_removed_at, (int, float))
                else None
            ),
        }
    )
    timeline_json, timeline_tsv = write_step_timeline(output_dir, timeline)
    source_info = source.get("info") or {}
    replay_info = replay.get("info") or {}
    source_commands = action_commands(source)
    replay_commands = action_commands(replay)
    source_rcs = action_returncodes(source)
    replay_rcs = action_returncodes(replay)
    source_patch = source_info.get("submission") or ""
    replay_patch = replay_info.get("submission") or ""

    checks = {
        "commands_match": source_commands == replay_commands,
        "returncodes_match": source_rcs == replay_rcs,
        "exit_status_match": source_info.get("exit_status") == replay_info.get("exit_status"),
        "patch_match": source_patch == replay_patch,
    }
    validation = {
        "format_version": 1,
        "instance_id": instance_id,
        "source_trajectory": str(source_path),
        "replay_trajectory": str(replay_path),
        "source_model": (source_info.get("config") or {}).get("model", {}).get("model_name"),
        "source_api_calls": (source_info.get("model_stats") or {}).get("api_calls"),
        "replayed_model_messages": len(outputs),
        "source_action_count": len(source_commands),
        "replay_action_count": len(replay_commands),
        "source_exit_status": source_info.get("exit_status"),
        "replay_exit_status": replay_info.get("exit_status"),
        "source_patch_sha256": sha256_text(source_patch),
        "replay_patch_sha256": sha256_text(replay_patch),
        "command_sequence_sha256": sha256_json(source_commands),
        "elapsed_seconds": elapsed,
        "started_at": started,
        "finished_at": finished,
        "delay_scale": args.delay_scale,
        "recorded_arrival_gap_sum_seconds": sum(action_arrival_delays(source)),
        "step_timeline_json": str(timeline_json),
        "step_timeline_tsv": str(timeline_tsv),
        "timeline": {key: value for key, value in timeline.items() if key != "steps"},
        "sandbox_lifecycle": lifecycle,
        "image": image_metadata(image) if image else {},
        "sde": {
            "enabled": args.sde,
            "home": str(sde_home) if sde_home else None,
            "output_dir": str(sde_output_dir) if sde_output_dir else None,
            "action_timeout_seconds": args.sde_action_timeout if args.sde else None,
            "max_actions": args.sde_max_actions if args.sde else None,
        },
        "checks": checks,
        "semantic_pass": checks["commands_match"] and checks["exit_status_match"] and checks["patch_match"],
        "strict_pass": all(checks.values()),
    }
    validation_path = output_dir / "replay_validation.json"
    validation_path.write_text(json.dumps(validation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(validation, ensure_ascii=False, indent=2))
    print(f"VALIDATION {validation_path}")
    if args.strict and not validation["strict_pass"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
