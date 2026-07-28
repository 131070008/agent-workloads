#!/usr/bin/env python3
"""Compute Intel EMR TMA 5.2 L1/L2 metrics from cgroup perf-stat CSV."""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path


EVENT_KEYS = {
    "slots": "cpu/slots/",
    "retiring": "cpu/topdown-retiring/",
    "bad_spec_raw": "cpu/topdown-bad-spec/",
    "frontend_raw": "cpu/topdown-fe-bound/",
    "backend": "cpu/topdown-be-bound/",
    "branch_mispredict": "cpu/topdown-br-mispredict/",
    "memory_bound": "cpu/topdown-mem-bound/",
    "heavy_operations": "cpu/topdown-heavy-ops/",
    "fetch_latency_raw": "cpu/topdown-fetch-lat/",
    "uop_dropping": "int_misc_uop_dropping",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output-csv", required=True, type=Path)
    parser.add_argument("--output-text", required=True, type=Path)
    return parser.parse_args()


def event_key(label: str) -> str | None:
    for key, needle in EVENT_KEYS.items():
        if needle in label:
            return key
    return None


def load_counts(path: Path) -> tuple[dict[str, dict[str, float]], list[float]]:
    counts: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    running: list[float] = []
    with path.open(encoding="utf-8") as stream:
        for row in csv.reader(stream):
            if not row or row[0].startswith("#") or len(row) < 6:
                continue
            try:
                value = float(row[1])
            except ValueError:
                continue
            key = event_key(row[3])
            if key is None:
                continue
            is_cgroup = len(row) >= 7 and (
                "/" in row[4]
                or row[4].endswith((".slice", ".scope", ".service"))
            )
            cgroup = row[4] if is_cgroup else "CPU0-7 global"
            counts[cgroup][key] += value
            try:
                running.append(float(row[6] if is_cgroup else row[5]))
            except ValueError:
                pass
    return counts, running


def divide(numerator: float, denominator: float, label: str) -> float:
    if denominator == 0:
        raise ValueError(f"zero denominator for {label}")
    return numerator / denominator


def compute(values: dict[str, float]) -> dict[str, float]:
    missing = sorted(set(EVENT_KEYS) - set(values))
    if missing:
        raise ValueError(f"missing events: {', '.join(missing)}")

    perf_metrics_sum = sum(
        values[key]
        for key in ("frontend_raw", "bad_spec_raw", "retiring", "backend")
    )
    dropped = divide(values["uop_dropping"], values["slots"], "uop dropping")
    frontend = divide(values["frontend_raw"], perf_metrics_sum, "frontend") - dropped
    backend = divide(values["backend"], perf_metrics_sum, "backend")
    retiring = divide(values["retiring"], perf_metrics_sum, "retiring")
    bad_speculation = max(1.0 - (frontend + backend + retiring), 0.0)

    fetch_latency = (
        divide(values["fetch_latency_raw"], perf_metrics_sum, "fetch latency")
        - dropped
    )
    branch_mispredicts = divide(
        values["branch_mispredict"], perf_metrics_sum, "branch mispredicts"
    )
    memory_bound = divide(
        values["memory_bound"], perf_metrics_sum, "memory bound"
    )
    heavy_operations = divide(
        values["heavy_operations"], perf_metrics_sum, "heavy operations"
    )

    return {
        "perf_metrics_sum_over_slots": divide(
            perf_metrics_sum, values["slots"], "PERF_METRICS closure"
        ),
        "uop_dropping_over_slots": dropped,
        "Frontend_Bound": frontend,
        "Bad_Speculation": bad_speculation,
        "Backend_Bound": backend,
        "Retiring": retiring,
        "Fetch_Latency": fetch_latency,
        "Fetch_Bandwidth": max(0.0, frontend - fetch_latency),
        "Branch_Mispredicts": branch_mispredicts,
        "Machine_Clears": max(0.0, bad_speculation - branch_mispredicts),
        "Memory_Bound": memory_bound,
        "Core_Bound": max(0.0, backend - memory_bound),
        "Heavy_Operations": heavy_operations,
        "Light_Operations": max(0.0, retiring - heavy_operations),
    }


def main() -> None:
    args = parse_args()
    counts, running = load_counts(args.input)
    if not counts:
        raise SystemExit(f"no cgroup Top-down events found in {args.input}")

    results = {cgroup: compute(values) for cgroup, values in counts.items()}
    metric_names = list(next(iter(results.values())))
    args.output_csv.parent.mkdir(parents=True, exist_ok=True)
    with args.output_csv.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["cgroup", "metric", "value", "unit"])
        for cgroup, metrics in results.items():
            for metric, value in metrics.items():
                unit = "ratio" if metric.endswith("_over_slots") else "percent"
                display_value = value if unit == "ratio" else value * 100
                writer.writerow([cgroup, metric, f"{display_value:.6f}", unit])

    lines = [
        "Intel EMR TMA 5.2 cgroup L1/L2",
        "=" * 88,
        f"Input: {args.input}",
        (
            f"Counter running: min={min(running):.2f}% max={max(running):.2f}%"
            if running
            else "Counter running: unavailable"
        ),
        "L1/L2 formulas are taken from Intel EMR metrics v1.4 / TMA 5.2.",
        "",
    ]
    for cgroup, metrics in results.items():
        lines.append(f"[{cgroup}]")
        lines.append(
            f"PERF_METRICS sum / slots = "
            f"{metrics['perf_metrics_sum_over_slots']:.6f}"
        )
        lines.append(
            f"UOP_DROPPING / slots = {metrics['uop_dropping_over_slots']:.6f}"
        )
        for metric in metric_names:
            if metric.endswith("_over_slots"):
                continue
            lines.append(f"{metric:24s} {metrics[metric] * 100:10.4f}%")
        lines.append("")
    args.output_text.write_text("\n".join(lines), encoding="utf-8")
    print(args.output_text)


if __name__ == "__main__":
    main()
