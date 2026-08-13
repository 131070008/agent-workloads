#!/usr/bin/env python3
"""Build a two-pass stable platform summary while retaining excluded cases."""

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
]


def load(path: Path) -> dict[str, dict[str, str]]:
    with path.open() as handle:
        return {row["instance_id"]: row for row in csv.DictReader(handle)}


def geomean(values: list[float]) -> float:
    return math.exp(sum(math.log(value) for value in values) / len(values))


def main() -> None:
    parser = argparse.ArgumentParser()
    for name in ("a1", "a2", "b1", "b2"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--a-name", default="a")
    parser.add_argument("--b-name", default="b")
    parser.add_argument("--exclude", nargs="*", default=[])
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    sets = {name: load(getattr(args, name) / "case_phases.csv") for name in ("a1", "a2", "b1", "b2")}
    ids = sorted(set.intersection(*(set(items) for items in sets.values())) - set(args.exclude))
    args.output_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    ratios = {metric: [] for metric in METRICS}
    for iid in ids:
        row: dict[str, str | float | int] = {"instance_id": iid, "tool_calls": int(sets["a1"][iid]["tool_calls"])}
        for metric in METRICS:
            a1 = float(sets["a1"][iid][metric])
            a2 = float(sets["a2"][iid][metric])
            b1 = float(sets["b1"][iid][metric])
            b2 = float(sets["b2"][iid][metric])
            a = math.sqrt(a1 * a2)
            b = math.sqrt(b1 * b2)
            ratio = b / a
            row[f"{args.a_name}_run1_{metric}"] = round(a1, 3)
            row[f"{args.a_name}_run2_{metric}"] = round(a2, 3)
            row[f"{args.a_name}_two_run_geomean_{metric}"] = round(a, 3)
            row[f"{args.b_name}_run1_{metric}"] = round(b1, 3)
            row[f"{args.b_name}_run2_{metric}"] = round(b2, 3)
            row[f"{args.b_name}_two_run_geomean_{metric}"] = round(b, 3)
            row[f"{args.b_name}_over_{args.a_name}_{metric}"] = round(ratio, 5)
            ratios[metric].append(ratio)
        rows.append(row)

    with (args.output_dir / "stable_paired_cases.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    summary = []
    for metric, values in ratios.items():
        ratio = geomean(values)
        summary.append({
            "metric": metric,
            "cases": len(values),
            f"{args.b_name}_over_{args.a_name}_paired_geomean": round(ratio, 5),
            f"{args.b_name}_extra_time_percent": round((ratio - 1.0) * 100.0, 3),
            f"{args.a_name}_lower_time_percent": round((1.0 - 1.0 / ratio) * 100.0, 3),
            "min_case_ratio": round(min(values), 5),
            "max_case_ratio": round(max(values), 5),
        })
    with (args.output_dir / "stable_phase_summary.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summary[0]))
        writer.writeheader()
        writer.writerows(summary)

    print(f"stable_cases={len(ids)} excluded={','.join(args.exclude)}")
    for row in summary:
        print(row["metric"], row[f"{args.b_name}_over_{args.a_name}_paired_geomean"])


if __name__ == "__main__":
    main()
