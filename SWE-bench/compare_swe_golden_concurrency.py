#!/usr/bin/env python3
"""Compare fixed-case Golden replay runs by instance ID and concurrency."""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any


STAGES = (
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


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def geometric_mean(values: list[float]) -> float | None:
    positive = [value for value in values if value > 0]
    return math.exp(sum(math.log(value) for value in positive) / len(positive)) if positive else None


def mean(records: list[dict[str, Any]], field: str) -> float:
    values = [float(record[field]) for record in records if record.get(field) is not None]
    if not values:
        return float("nan")
    return sum(values) / len(values)


def e2e_field(records: list[dict[str, Any]]) -> str:
    return (
        "sandbox_e2e_seconds"
        if all(record.get("sandbox_e2e_seconds") is not None for record in records)
        else "service_e2e_seconds"
    )


def parse_run(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("run must be LABEL=/path/to/run")
    label, path = value.split("=", 1)
    return label, Path(path).expanduser().resolve()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="append", type=parse_run, required=True)
    parser.add_argument("--baseline", default="k1")
    parser.add_argument("--primary", default="")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    runs = dict(args.run)
    if args.baseline not in runs:
        raise SystemExit(f"baseline not found: {args.baseline}")
    args.output_dir.mkdir(parents=True, exist_ok=True)

    summaries = {
        label: read_json(path / "performance_summary.json") for label, path in runs.items()
    }
    records: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for label, summary in summaries.items():
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for record in summary["cases"]:
            grouped[record["instance_id"]].append(record)
        records[label] = dict(grouped)
    baseline_cases = set(records[args.baseline])
    for label, cases in records.items():
        if set(cases) != baseline_cases:
            missing = sorted(baseline_cases - set(cases))
            extra = sorted(set(cases) - baseline_cases)
            raise SystemExit(f"case-set mismatch for {label}: missing={missing}, extra={extra}")

    rows: list[dict[str, Any]] = []
    ratios: dict[str, list[float]] = {label: [] for label in runs}
    for instance_id in sorted(baseline_cases):
        baseline_records = records[args.baseline][instance_id]
        baseline_e2e = mean(baseline_records, e2e_field(baseline_records))
        for label in runs:
            case_records = records[label][instance_id]
            primary_e2e_field = e2e_field(case_records)
            e2e_values = [float(record[primary_e2e_field]) for record in case_records]
            ratio = mean(case_records, primary_e2e_field) / baseline_e2e
            ratios[label].append(ratio)
            rows.append(
                {
                    "instance_id": instance_id,
                    "concurrency": label,
                    "runs": len(case_records),
                    **{stage: mean(case_records, stage) for stage in STAGES},
                    "e2e_min_seconds": min(e2e_values),
                    "e2e_max_seconds": max(e2e_values),
                    "slowdown_vs_baseline": ratio,
                    "step_count": case_records[0]["step_count"],
                    "semantic_pass": all(record["semantic_pass"] for record in case_records),
                }
            )

    columns = (
        "instance_id",
        "concurrency",
        "runs",
        *STAGES,
        "e2e_min_seconds",
        "e2e_max_seconds",
        "slowdown_vs_baseline",
        "step_count",
        "semantic_pass",
    )
    with (args.output_dir / "per_case_concurrency.tsv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)

    run_summary = []
    for label, summary in summaries.items():
        run_summary.append(
            {
                "concurrency": label,
                "case_count": len(records[label]),
                "batch_makespan_seconds": summary["elapsed_seconds"],
                "batch_throughput_cases_per_second": summary["throughput_cases_per_second"],
                "cpu_utilization_mean_percent": summary["cpu_utilization_mean_percent"],
                "case_service_e2e_seconds": summary["case_service_e2e_seconds"],
                "case_arrival_e2e_seconds": summary["case_arrival_e2e_seconds"],
                "case_sandbox_e2e_seconds": summary["case_sandbox_e2e_seconds"],
                "paired_geomean_slowdown_vs_baseline": geometric_mean(ratios[label]),
            }
        )
    comparison = {
        "baseline": args.baseline,
        "case_set": sorted(baseline_cases),
        "runs": run_summary,
        "per_case_rows": rows,
    }
    (args.output_dir / "concurrency_comparison.json").write_text(
        json.dumps(comparison, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    with (args.output_dir / "concurrency_summary.tsv").open("w", newline="", encoding="utf-8") as stream:
        columns = (
            "concurrency",
            "case_count",
            "batch_makespan_seconds",
            "batch_throughput_cases_per_second",
            "cpu_utilization_mean_percent",
            "paired_geomean_slowdown_vs_baseline",
        )
        writer = csv.DictWriter(stream, fieldnames=columns, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(run_summary)

    if args.primary:
        if args.primary not in runs:
            raise SystemExit(f"primary run not found: {args.primary}")
        pair_rows = []
        for instance_id in sorted(baseline_cases):
            baseline_records = records[args.baseline][instance_id]
            primary_records = records[args.primary][instance_id]
            baseline_e2e = mean(baseline_records, e2e_field(baseline_records))
            primary_e2e = mean(primary_records, e2e_field(primary_records))
            row: dict[str, Any] = {
                "instance_id": instance_id,
                "baseline": args.baseline,
                "primary": args.primary,
                "baseline_runs": len(baseline_records),
                "primary_runs": len(primary_records),
                "slowdown_vs_baseline": primary_e2e / baseline_e2e,
            }
            for stage in STAGES:
                row[f"baseline_{stage}"] = mean(baseline_records, stage)
                row[f"primary_{stage}"] = mean(primary_records, stage)
            pair_rows.append(row)
        pair_columns = tuple(pair_rows[0])
        pair_path = args.output_dir / f"per_case_{args.baseline}_vs_{args.primary}.tsv"
        with pair_path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=pair_columns, delimiter="\t")
            writer.writeheader()
            writer.writerows(pair_rows)
    print(json.dumps({"output_dir": str(args.output_dir), "runs": run_summary}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
