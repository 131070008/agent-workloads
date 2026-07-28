#!/usr/bin/env python3
"""Package recorded SWE trajectories and metadata as a portable Golden Set."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_json(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256_bytes(payload)


def read_cases(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream, delimiter="\t"))


def find_latest(roots: list[Path], pattern: str) -> Path | None:
    candidates = [path for root in roots for path in root.glob(pattern)]
    return max(candidates, key=lambda path: path.stat().st_mtime) if candidates else None


def find_latest_terminal_trajectory(roots: list[Path], instance_id: str) -> Path | None:
    candidates = []
    for root in roots:
        for path in root.glob(f"**/{instance_id}.traj.json"):
            trajectory = read_json(path, {}) or {}
            if ((trajectory.get("info") or {}).get("exit_status")):
                candidates.append(path)
    return max(candidates, key=lambda path: path.stat().st_mtime) if candidates else None


def docker_images(references: list[str]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for reference in sorted(set(filter(None, references))):
        completed = subprocess.run(
            ["docker", "image", "inspect", reference],
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            result[reference] = {"reference": reference, "inspect_error": completed.stderr.strip()}
            continue
        inspected = json.loads(completed.stdout)[0]
        result[reference] = {
            "reference": reference,
            "image_id": inspected.get("Id", ""),
            "repo_digests": inspected.get("RepoDigests") or [],
            "platform": f"{inspected.get('Os', '')}/{inspected.get('Architecture', '')}",
            "size_bytes": inspected.get("Size"),
        }
    return result


def token_usage(messages: list[dict[str, Any]]) -> dict[str, int]:
    totals = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "cached_tokens": 0}
    for message in messages:
        if message.get("role") != "assistant":
            continue
        usage = ((message.get("extra") or {}).get("response") or {}).get("usage") or {}
        totals["prompt_tokens"] += int(usage.get("prompt_tokens", 0) or 0)
        totals["completion_tokens"] += int(usage.get("completion_tokens", 0) or 0)
        totals["total_tokens"] += int(usage.get("total_tokens", 0) or 0)
        cached_tokens = usage.get("prompt_cache_hit_tokens")
        if cached_tokens is None:
            cached_tokens = (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0)
        totals["cached_tokens"] += int(cached_tokens or 0)
    return totals


def trajectory_metrics(trajectory: dict[str, Any], run_meta: dict[str, Any]) -> dict[str, Any]:
    info = trajectory.get("info") or {}
    messages = trajectory.get("messages") or []
    commands: list[str] = []
    returncodes: list[int | None] = []
    arrival_gaps: list[float] = []
    command_times: list[float] = []
    previous_done = run_meta.get("started_at")

    for index, message in enumerate(messages):
        if message.get("role") != "assistant":
            continue
        extra = message.get("extra") or {}
        actions = extra.get("actions") or []
        if not actions:
            continue
        response_done = extra.get("timestamp")
        if isinstance(previous_done, (int, float)) and isinstance(response_done, (int, float)):
            arrival_gaps.append(max(0.0, response_done - previous_done))
        commands.extend(str(action.get("command", "")) for action in actions)

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
        if observation:
            observation_extra = observation["extra"]
            observation_done = observation_extra.get("timestamp")
            returncodes.append(observation_extra.get("returncode"))
            if isinstance(response_done, (int, float)) and isinstance(observation_done, (int, float)):
                command_times.append(max(0.0, observation_done - response_done))
            previous_done = observation_done

    api_calls = int((info.get("model_stats") or {}).get("api_calls", 0) or 0)
    patch = info.get("submission") or ""
    return {
        "source_model": (info.get("config") or {}).get("model", {}).get("model_name"),
        "mini_swe_agent_version": info.get("mini_version"),
        "exit_status": info.get("exit_status"),
        "api_calls": api_calls,
        "replayable_action_count": len(commands),
        "non_action_model_calls": max(0, api_calls - len(commands)),
        "command_sequence_sha256": sha256_json(commands),
        "returncode_sequence": returncodes,
        "patch_chars": len(patch),
        "patch_sha256": sha256_bytes(patch.encode("utf-8")),
        "token_usage": token_usage(messages),
        "arrival_gap_seconds": arrival_gaps,
        "command_time_seconds": command_times,
        "arrival_gap_sum_seconds": sum(arrival_gaps),
        "command_time_sum_seconds": sum(command_times),
    }


def evaluator_result(
    roots: list[Path],
    instance_id: str,
    batch_report: dict[str, Any],
) -> dict[str, Any]:
    if batch_report:
        resolved_ids = set(batch_report.get("resolved_ids") or [])
        unresolved_ids = set(batch_report.get("unresolved_ids") or [])
        error_ids = set(batch_report.get("error_ids") or [])
        if instance_id in resolved_ids | unresolved_ids | error_ids:
            return {
                "resolved_instances": int(instance_id in resolved_ids),
                "unresolved_instances": int(instance_id in unresolved_ids),
                "error_instances": int(instance_id in error_ids),
                "source": "batch_report",
            }
    status_path = find_latest(roots, f"**/{instance_id}/case_status.json")
    if not status_path:
        return {}
    status = read_json(status_path, {}) or {}
    result = status.get("eval") or {}
    return {
        key: result.get(key)
        for key in ("resolved_instances", "unresolved_instances", "error_instances", "report_path")
        if key in result
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", required=True)
    parser.add_argument("--selected-tsv", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, action="append", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--evaluation-report", type=Path)
    args = parser.parse_args()
    selected_tsv = args.selected_tsv.expanduser().resolve()
    roots = [root.expanduser().resolve() for root in args.source_root]
    output_dir = args.output_dir.expanduser().resolve()
    trajectories_dir = output_dir / "trajectories"
    trajectories_dir.mkdir(parents=True, exist_ok=True)
    batch_report = (
        read_json(args.evaluation_report.expanduser().resolve(), {})
        if args.evaluation_report
        else {}
    )

    cases = read_cases(selected_tsv)
    manifest_cases: list[dict[str, Any]] = []
    image_references: list[str] = []
    checksums: list[str] = []
    missing: list[str] = []
    for row in cases:
        instance_id = row["instance_id"]
        source_path = find_latest_terminal_trajectory(roots, instance_id)
        if not source_path:
            missing.append(instance_id)
            continue
        trajectory = read_json(source_path, {}) or {}
        run_meta_path = source_path.parents[1] / "run_meta_start.json"
        run_meta = read_json(run_meta_path, {}) or {}
        destination = trajectories_dir / f"{instance_id}.traj.json"
        shutil.copy2(source_path, destination)
        trajectory_hash = sha256_file(destination)
        checksums.append(f"{trajectory_hash}  trajectories/{destination.name}")
        environment = ((trajectory.get("info") or {}).get("config") or {}).get("environment") or {}
        image = environment.get("image") or row.get("image") or ""
        image_references.append(image)
        manifest_cases.append(
            {
                "instance_id": instance_id,
                "repo": row.get("repo"),
                "image": image,
                "source_trajectory": str(source_path),
                "trajectory_file": f"trajectories/{destination.name}",
                "trajectory_sha256": trajectory_hash,
                "metrics": trajectory_metrics(trajectory, run_meta),
                "evaluator": evaluator_result(roots, instance_id, batch_report),
            }
        )

    images = docker_images(image_references)
    aggregate = {
        "case_count": len(manifest_cases),
        "missing_count": len(missing),
        "api_calls": sum(case["metrics"]["api_calls"] for case in manifest_cases),
        "replayable_actions": sum(case["metrics"]["replayable_action_count"] for case in manifest_cases),
        "non_action_model_calls": sum(case["metrics"]["non_action_model_calls"] for case in manifest_cases),
        "token_usage": {
            key: sum(case["metrics"]["token_usage"][key] for case in manifest_cases)
            for key in ("prompt_tokens", "completion_tokens", "total_tokens", "cached_tokens")
        },
        "exit_statuses": {},
        "evaluator": {
            "resolved": sum((case.get("evaluator") or {}).get("resolved_instances") == 1 for case in manifest_cases),
            "unresolved": sum((case.get("evaluator") or {}).get("unresolved_instances") == 1 for case in manifest_cases),
            "errors": sum((case.get("evaluator") or {}).get("error_instances") == 1 for case in manifest_cases),
        },
    }
    for case in manifest_cases:
        status = case["metrics"]["exit_status"] or "unknown"
        aggregate["exit_statuses"][status] = aggregate["exit_statuses"].get(status, 0) + 1

    manifest = {
        "format_version": 1,
        "label": args.label,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "selected_cases": str(selected_tsv),
        "source_roots": [str(root) for root in roots],
        "aggregate": aggregate,
        "missing_instances": missing,
        "images": images,
        "cases": manifest_cases,
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output_dir / "checksums.sha256").write_text("\n".join(checksums) + "\n", encoding="utf-8")
    shutil.copy2(selected_tsv, output_dir / "selected_cases.tsv")
    print(json.dumps({"output_dir": str(output_dir), "aggregate": aggregate, "missing": missing}, ensure_ascii=False, indent=2))
    if missing:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
