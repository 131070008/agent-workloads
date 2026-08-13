#!/usr/bin/env python3
"""Pair fixed-trajectory SWE timing results from two platforms."""

from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path


METRICS = [
    "full_wall_ms",
    "main_total_ms",
    "environment_start_ms",
    "agent_setup_ms",
    "step_total_ms",
    "tool_and_submission_ms",
    "communicate_ms",
    "history_integrate_ms",
    "environment_close_ms",
    "other_main_ms",
]


def read_cases(path: Path) -> dict[str, dict[str, str]]:
    with path.open() as handle:
        return {row["instance_id"]: row for row in csv.DictReader(handle)}


def geomean(values: list[float]) -> float:
    return math.exp(sum(math.log(value) for value in values) / len(values))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--baseline-name", default="baseline")
    parser.add_argument("--candidate-name", default="candidate")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    baseline = read_cases(args.baseline / "case_phases.csv")
    candidate = read_cases(args.candidate / "case_phases.csv")
    case_ids = sorted(set(baseline) & set(candidate))
    if len(case_ids) != 38:
        raise SystemExit(f"Expected 38 paired cases, found {len(case_ids)}")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    paired_rows: list[dict[str, str | float | int]] = []
    ratios: dict[str, list[float]] = {metric: [] for metric in METRICS}
    for instance_id in case_ids:
        left = baseline[instance_id]
        right = candidate[instance_id]
        row: dict[str, str | float | int] = {
            "instance_id": instance_id,
            f"{args.baseline_name}_status": left["status"],
            f"{args.candidate_name}_status": right["status"],
            "tool_calls": int(left["tool_calls"]),
        }
        for metric in METRICS:
            left_value = float(left[metric])
            right_value = float(right[metric])
            ratio = right_value / left_value if left_value else float("nan")
            row[f"{args.baseline_name}_{metric}"] = round(left_value, 3)
            row[f"{args.candidate_name}_{metric}"] = round(right_value, 3)
            row[f"{args.candidate_name}_over_{args.baseline_name}_{metric}"] = round(ratio, 5)
            if math.isfinite(ratio) and ratio > 0:
                ratios[metric].append(ratio)
        paired_rows.append(row)

    with (args.output_dir / "paired_case_comparison.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(paired_rows[0]))
        writer.writeheader()
        writer.writerows(paired_rows)

    summary_rows = []
    for metric in METRICS:
        values = ratios[metric]
        summary_rows.append({
            "metric": metric,
            "paired_cases": len(values),
            f"{args.candidate_name}_over_{args.baseline_name}_geomean": round(geomean(values), 5),
            f"{args.baseline_name}_faster_percent": round((geomean(values) - 1.0) * 100.0, 3),
            "min_ratio": round(min(values), 5),
            "max_ratio": round(max(values), 5),
        })
    with (args.output_dir / "phase_geomean_summary.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summary_rows[0]))
        writer.writeheader()
        writer.writerows(summary_rows)

    print(f"paired_cases={len(case_ids)}")
    for row in summary_rows:
        print(
            f"{row['metric']}: {args.candidate_name}/{args.baseline_name}="
            f"{row[f'{args.candidate_name}_over_{args.baseline_name}_geomean']}"
        )


if __name__ == "__main__":
    main()
