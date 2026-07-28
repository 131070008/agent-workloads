#!/usr/bin/env python3
"""Summarize Golden replay latency, throughput, CPU utilization, and step mix."""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

from replay_swe_trajectory import command_category, write_step_timeline


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


def summarize_values(values: list[float]) -> dict[str, float | int | None]:
    return {
        "count": len(values),
        "min": min(values) if values else None,
        "mean": sum(values) / len(values) if values else None,
        "p50": percentile(values, 0.50),
        "p90": percentile(values, 0.90),
        "p99": percentile(values, 0.99),
        "max": max(values) if values else None,
    }


def case_record(
    validation_path: Path,
    job: dict[str, Any] | None = None,
    batch_started_at: float | None = None,
) -> dict[str, Any]:
    validation = read_json(validation_path, {}) or {}
    timeline = read_json(validation_path.parent / "step_timeline.json", {}) or {}
    category_seconds: dict[str, float] = defaultdict(float)
    category_steps: dict[str, int] = defaultdict(int)
    for step in timeline.get("steps") or []:
        category = command_category(step.get("commands") or [])
        category_steps[category] += 1
        category_seconds[category] += float(step.get("tool_wall_seconds") or 0.0)

    startup = float(timeline.get("startup_to_first_action_seconds") or 0.0)
    control = float(timeline.get("action_gap_sum_seconds") or 0.0)
    tools = float(timeline.get("tool_wall_sum_seconds") or 0.0)
    finish = float(timeline.get("last_observation_to_finish_seconds") or 0.0)
    sandbox_e2e = timeline.get("sandbox_e2e_seconds")
    container_start = timeline.get("container_start_seconds")
    agent_init = timeline.get("agent_init_after_container_seconds")
    result_capture = timeline.get("result_capture_seconds")
    container_teardown = timeline.get("container_teardown_seconds")
    lifecycle_values = (
        sandbox_e2e,
        container_start,
        agent_init,
        result_capture,
        container_teardown,
    )
    has_lifecycle = all(value is not None for value in lifecycle_values)
    lifecycle_total = (
        float(container_start)
        + float(agent_init)
        + control
        + tools
        + float(result_capture)
        + float(container_teardown)
        if has_lifecycle
        else None
    )
    process_instance = float(validation.get("elapsed_seconds") or 0.0)
    service_e2e = float((job or {}).get("elapsed_seconds") or process_instance)
    started_at = (job or {}).get("started_at")
    finished_at = (job or {}).get("finished_at")
    submitted_at = (job or {}).get("submitted_at") or batch_started_at or started_at
    queue_wait = (
        max(0.0, float(started_at) - float(submitted_at))
        if started_at is not None and submitted_at is not None
        else 0.0
    )
    arrival_e2e = (
        max(0.0, float(finished_at) - float(submitted_at))
        if finished_at is not None and submitted_at is not None
        else service_e2e
    )
    repeat_name = validation_path.parent.parent.name
    repeat = int(repeat_name.removeprefix("repeat_")) if repeat_name.startswith("repeat_") else None
    return {
        "instance_id": validation.get("instance_id"),
        "repeat": repeat,
        "e2e_seconds": service_e2e,
        "sandbox_e2e_seconds": float(sandbox_e2e) if sandbox_e2e is not None else None,
        "container_start_seconds": (
            float(container_start) if container_start is not None else None
        ),
        "agent_init_after_container_seconds": (
            float(agent_init) if agent_init is not None else None
        ),
        "result_capture_seconds": (
            float(result_capture) if result_capture is not None else None
        ),
        "container_teardown_seconds": (
            float(container_teardown) if container_teardown is not None else None
        ),
        "sandbox_unattributed_seconds": (
            max(0.0, float(sandbox_e2e) - lifecycle_total)
            if has_lifecycle and lifecycle_total is not None
            else None
        ),
        "service_e2e_seconds": service_e2e,
        "arrival_e2e_seconds": arrival_e2e,
        "queue_wait_seconds": queue_wait,
        "replay_process_overhead_seconds": max(0.0, service_e2e - process_instance),
        "process_instance_seconds": process_instance,
        "startup_to_first_action_seconds": startup,
        "agent_control_gap_seconds": control,
        "tool_wall_seconds": tools,
        "finish_tail_seconds": finish,
        "unattributed_seconds": max(
            0.0, process_instance - startup - control - tools - finish
        ),
        "step_count": int(timeline.get("step_count") or 0),
        "tool_category_seconds": dict(sorted(category_seconds.items())),
        "tool_category_steps": dict(sorted(category_steps.items())),
        "semantic_pass": validation.get("semantic_pass"),
        "output_dir": str(validation_path.parent),
    }


def summarize_by_instance(records: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[str(record["instance_id"])].append(record)
    stage_names = (
        "sandbox_e2e_seconds",
        "container_start_seconds",
        "agent_init_after_container_seconds",
        "agent_control_gap_seconds",
        "tool_wall_seconds",
        "result_capture_seconds",
        "container_teardown_seconds",
        "sandbox_unattributed_seconds",
        "service_e2e_seconds",
        "arrival_e2e_seconds",
        "queue_wait_seconds",
        "replay_process_overhead_seconds",
        "process_instance_seconds",
        "startup_to_first_action_seconds",
        "finish_tail_seconds",
        "unattributed_seconds",
    )
    result: dict[str, Any] = {}
    for instance_id, case_records in sorted(grouped.items()):
        result[instance_id] = {
            "runs": len(case_records),
            "stages": {
                stage: summarize_values(
                    [
                        float(record[stage])
                        for record in case_records
                        if record.get(stage) is not None
                    ]
                )
                for stage in stage_names
            },
        }
    return result


def read_cpu_stat(path: Path) -> dict[str, tuple[int, int]]:
    result: dict[str, tuple[int, int]] = {}
    if not path.exists():
        return result
    for line in path.read_text(encoding="utf-8").splitlines():
        fields = line.split()
        if not fields or not fields[0].startswith("cpu") or fields[0] == "cpu":
            continue
        values = [int(value) for value in fields[1:]]
        total = sum(values)
        idle = values[3] + (values[4] if len(values) > 4 else 0)
        result[fields[0]] = (total, idle)
    return result


def cpu_utilization(start: Path, end: Path) -> dict[str, float]:
    before = read_cpu_stat(start)
    after = read_cpu_stat(end)
    result: dict[str, float] = {}
    for cpu in sorted(before):
        if cpu not in after:
            continue
        total = after[cpu][0] - before[cpu][0]
        idle = after[cpu][1] - before[cpu][1]
        if total > 0:
            result[cpu] = 100.0 * (total - idle) / total
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    output_dir = args.output_dir.expanduser().resolve()
    batch = read_json(output_dir / "replay_summary.json", {}) or {}
    config = batch.get("config") or {}
    jobs_by_output = {
        str(Path(job["output_dir"]).resolve()): job
        for job in batch.get("jobs") or []
        if job.get("output_dir")
    }
    validation_paths = sorted(output_dir.glob("**/replay_validation.json"))
    validations = [read_json(path, {}) for path in validation_paths]
    case_records = [
        case_record(
            path,
            jobs_by_output.get(str(path.parent.resolve())),
            config.get("started_at"),
        )
        for path in validation_paths
    ]
    timelines = []
    for path in output_dir.glob("**/step_timeline.json"):
        timeline = read_json(path, {})
        for step in timeline.get("steps") or []:
            step["category"] = command_category(step.get("commands") or [])
        write_step_timeline(path.parent, timeline)
        timelines.append(timeline)
    service_latencies = [float(record["service_e2e_seconds"]) for record in case_records]
    arrival_latencies = [float(record["arrival_e2e_seconds"]) for record in case_records]
    sandbox_latencies = [
        float(record["sandbox_e2e_seconds"])
        for record in case_records
        if record.get("sandbox_e2e_seconds") is not None
    ]
    wall_clock = read_json(output_dir / "run_wall_clock.json", {}) or {}
    elapsed = wall_clock.get("elapsed_seconds") or config.get("elapsed_seconds")
    if elapsed is None and validations:
        starts = [item.get("started_at") for item in validations if item.get("started_at")]
        finishes = [item.get("finished_at") for item in validations if item.get("finished_at")]
        elapsed = (
            max(finishes) - min(starts)
            if starts and finishes
            else sum(service_latencies)
        )

    categories: dict[str, dict[str, float | int]] = {}
    for timeline in timelines:
        for step in timeline.get("steps") or []:
            category = str(step.get("category") or "unknown")
            entry = categories.setdefault(category, {"steps": 0, "tool_wall_seconds": 0.0})
            entry["steps"] = int(entry["steps"]) + 1
            entry["tool_wall_seconds"] = float(entry["tool_wall_seconds"]) + float(
                step.get("tool_wall_seconds") or 0.0
            )

    cpu = cpu_utilization(output_dir / "cpu_stat_start.txt", output_dir / "cpu_stat_end.txt")
    summary = {
        "output_dir": str(output_dir),
        "completed_cases": len(validations),
        "elapsed_seconds": elapsed,
        "throughput_cases_per_second": len(validations) / elapsed if elapsed else None,
        "case_latency_seconds": summarize_values(service_latencies),
        "case_sandbox_e2e_seconds": summarize_values(sandbox_latencies),
        "case_service_e2e_seconds": summarize_values(service_latencies),
        "case_arrival_e2e_seconds": summarize_values(arrival_latencies),
        "cases": case_records,
        "by_instance": summarize_by_instance(case_records),
        "cpu_utilization_percent": cpu,
        "cpu_utilization_mean_percent": sum(cpu.values()) / len(cpu) if cpu else None,
        "step_categories": categories,
    }
    (output_dir / "performance_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                key: summary[key]
                for key in (
                    "output_dir",
                    "completed_cases",
                    "elapsed_seconds",
                    "throughput_cases_per_second",
                    "case_latency_seconds",
                    "cpu_utilization_mean_percent",
                    "step_categories",
                )
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
