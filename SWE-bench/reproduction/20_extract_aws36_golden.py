#!/usr/bin/env python3
"""Validate a two-round AWS36 run and export round 1 as the Golden dataset."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PHASE_FIELDS = (
    "full_wall_ms",
    "import_and_outer_ms",
    "main_total_ms",
    "environment_start_ms",
    "agent_setup_ms",
    "step_total_ms",
    "action_parse_ms",
    "tool_and_submission_ms",
    "communicate_ms",
    "history_integrate_ms",
    "environment_close_ms",
    "other_main_ms",
    "step_residual_ms",
)

REQUIRED_ROUND_FILES = (
    "run_info.tsv",
    "status.tsv",
    "case_phases.csv",
    "tool_calls.csv",
    "category_summary.csv",
    "final_summary.txt",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Export round1 as the official Golden result. Round2 is checked only "
            "for completeness and is never averaged into the exported metrics."
        )
    )
    parser.add_argument("--series-dir", type=Path, required=True)
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Output directory (default: SERIES_DIR/golden)",
    )
    parser.add_argument("--expected-cases", type=int, default=36)
    parser.add_argument("--expected-tool-calls", type=int, default=1270)
    return parser.parse_args()


def read_csv(path: Path, delimiter: str = ",") -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=delimiter)
        if reader.fieldnames is None:
            raise ValueError(f"Missing header: {path}")
        return list(reader.fieldnames), list(reader)


def read_key_value(path: Path, delimiter: str) -> dict[str, str]:
    values: dict[str, str] = {}
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.rstrip("\n")
            if not line:
                continue
            if delimiter not in line:
                raise ValueError(f"Malformed line {line_number} in {path}: {line!r}")
            key, value = line.split(delimiter, 1)
            values[key] = value
    return values


def integer(value: str, field: str, path: Path) -> int:
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"Invalid integer for {field} in {path}: {value!r}") from exc


def number(value: str, field: str, path: Path) -> float:
    try:
        result = float(value)
    except ValueError as exc:
        raise ValueError(f"Invalid number for {field} in {path}: {value!r}") from exc
    if not math.isfinite(result):
        raise ValueError(f"Non-finite number for {field} in {path}: {value!r}")
    return result


def is_true(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes"}


def percentile(values: list[float], fraction: float) -> float:
    """Return a linearly interpolated percentile over an already finite sample."""
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def require_columns(path: Path, fields: list[str], required: set[str]) -> None:
    missing = sorted(required - set(fields))
    if missing:
        raise ValueError(f"Missing columns in {path}: {', '.join(missing)}")


def validate_round(
    round_dir: Path,
    expected_cases: int,
    expected_tool_calls: int,
) -> dict[str, Any]:
    for name in REQUIRED_ROUND_FILES:
        path = round_dir / name
        if not path.is_file():
            raise FileNotFoundError(f"Missing required result file: {path}")

    run_info = read_key_value(round_dir / "run_info.tsv", "\t")
    final = read_key_value(round_dir / "final_summary.txt", "=")
    for field, expected in (
        ("cases", expected_cases),
        ("pass", expected_cases),
        ("incomplete", 0),
        ("fail", 0),
    ):
        actual = integer(final.get(field, ""), field, round_dir / "final_summary.txt")
        if actual != expected:
            raise ValueError(
                f"{round_dir.name} has {field}={actual}; expected {expected}"
            )

    status_fields, status_rows = read_csv(round_dir / "status.tsv", delimiter="\t")
    require_columns(
        round_dir / "status.tsv",
        status_fields,
        {"instance_id", "status", "exit_code", "replay_calls", "expected_calls"},
    )
    if len(status_rows) != expected_cases:
        raise ValueError(
            f"{round_dir.name} has {len(status_rows)} status rows; expected {expected_cases}"
        )
    status_ids = [row["instance_id"] for row in status_rows]
    if len(set(status_ids)) != expected_cases:
        raise ValueError(f"Duplicate instance_id in {round_dir / 'status.tsv'}")
    for row in status_rows:
        if row["status"] != "PASS" or row["exit_code"] != "0":
            raise ValueError(
                f"Incomplete case in {round_dir.name}: {row['instance_id']} "
                f"status={row['status']} exit_code={row['exit_code']}"
            )
        replay_calls = integer(
            row["replay_calls"], "replay_calls", round_dir / "status.tsv"
        )
        expected_calls = integer(
            row["expected_calls"], "expected_calls", round_dir / "status.tsv"
        )
        if replay_calls < expected_calls:
            raise ValueError(f"Replay call shortage for {row['instance_id']} in {round_dir.name}")

    phase_fields, phase_rows = read_csv(round_dir / "case_phases.csv")
    require_columns(
        round_dir / "case_phases.csv",
        phase_fields,
        {
            "instance_id",
            "status",
            "tool_calls",
            "expected_replay_calls",
            "autosubmit_calls",
            "replay_complete",
            *PHASE_FIELDS,
        },
    )
    if len(phase_rows) != expected_cases:
        raise ValueError(
            f"{round_dir.name} has {len(phase_rows)} phase rows; expected {expected_cases}"
        )
    phase_ids = [row["instance_id"] for row in phase_rows]
    if set(phase_ids) != set(status_ids):
        raise ValueError(f"Case IDs differ between status.tsv and case_phases.csv in {round_dir}")
    phase_tool_calls = 0
    for row in phase_rows:
        if row["status"] != "PASS" or not is_true(row["replay_complete"]):
            raise ValueError(f"Incomplete phase row for {row['instance_id']} in {round_dir.name}")
        calls = integer(row["tool_calls"], "tool_calls", round_dir / "case_phases.csv")
        expected = integer(
            row["expected_replay_calls"],
            "expected_replay_calls",
            round_dir / "case_phases.csv",
        )
        autosubmit = integer(
            row["autosubmit_calls"], "autosubmit_calls", round_dir / "case_phases.csv"
        )
        if calls != expected + autosubmit:
            raise ValueError(
                f"ToolCall mismatch for {row['instance_id']} in {round_dir.name}: "
                f"calls={calls}, replay={expected}, autosubmit={autosubmit}"
            )
        phase_tool_calls += calls
        for field in PHASE_FIELDS:
            if number(row[field], field, round_dir / "case_phases.csv") < 0:
                raise ValueError(f"Negative {field} for {row['instance_id']} in {round_dir.name}")

    tool_fields, tool_rows = read_csv(round_dir / "tool_calls.csv")
    require_columns(
        round_dir / "tool_calls.csv",
        tool_fields,
        {
            "instance_id",
            "tool_index",
            "tool_name",
            "category",
            "tool_e2e_ms",
            "communicate_ms",
            "framework_tail_ms",
            "command",
        },
    )
    if len(tool_rows) != expected_tool_calls or phase_tool_calls != expected_tool_calls:
        raise ValueError(
            f"{round_dir.name} ToolCall count mismatch: CSV={len(tool_rows)}, "
            f"case sum={phase_tool_calls}, expected={expected_tool_calls}"
        )
    if {row["instance_id"] for row in tool_rows} - set(status_ids):
        raise ValueError(f"Unknown instance_id in {round_dir / 'tool_calls.csv'}")

    category_fields, category_rows = read_csv(round_dir / "category_summary.csv")
    require_columns(
        round_dir / "category_summary.csv",
        category_fields,
        {"category", "calls", "tool_e2e_ms", "share_percent"},
    )
    category_calls = sum(
        integer(row["calls"], "calls", round_dir / "category_summary.csv")
        for row in category_rows
    )
    if category_calls != expected_tool_calls:
        raise ValueError(
            f"{round_dir.name} category calls={category_calls}; expected={expected_tool_calls}"
        )

    return {
        "run_info": run_info,
        "final": final,
        "status_fields": status_fields,
        "status_rows": status_rows,
        "phase_fields": phase_fields,
        "phase_rows": phase_rows,
        "tool_fields": tool_fields,
        "tool_rows": tool_rows,
        "category_fields": category_fields,
        "category_rows": category_rows,
        "case_ids": set(status_ids),
    }


def atomic_write_csv(
    path: Path,
    fields: list[str],
    rows: list[dict[str, Any]],
    delimiter: str = ",",
) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter=delimiter)
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temporary, path)


def atomic_write_text(path: Path, content: str) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, path)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    args = parse_args()
    series_dir = args.series_dir.expanduser().resolve()
    output_dir = (args.output_dir or series_dir / "golden").expanduser().resolve()
    rounds_path = series_dir / "rounds.tsv"
    if not rounds_path.is_file():
        raise FileNotFoundError(f"Missing round status file: {rounds_path}")

    round_fields, round_rows = read_csv(rounds_path, delimiter="\t")
    require_columns(rounds_path, round_fields, {"round", "status", "exit_code"})
    rounds = {row["round"]: row for row in round_rows}
    for round_number in ("1", "2"):
        row = rounds.get(round_number)
        if row is None:
            raise ValueError(f"Missing round {round_number} in {rounds_path}")
        if row["status"] != "PASS" or row["exit_code"] != "0":
            raise ValueError(
                f"Round {round_number} did not pass: "
                f"status={row['status']} exit_code={row['exit_code']}"
            )

    primary = validate_round(
        series_dir / "round1", args.expected_cases, args.expected_tool_calls
    )
    validation = validate_round(
        series_dir / "round2", args.expected_cases, args.expected_tool_calls
    )
    if primary["case_ids"] != validation["case_ids"]:
        raise ValueError("Round 1 and round 2 contain different case IDs")

    output_dir.mkdir(parents=True, exist_ok=True)
    output_files: list[Path] = []

    exports = (
        (
            "golden_case_phases.csv",
            primary["phase_fields"],
            primary["phase_rows"],
            ",",
        ),
        (
            "golden_tool_calls.csv",
            primary["tool_fields"],
            primary["tool_rows"],
            ",",
        ),
        (
            "golden_category_summary.csv",
            primary["category_fields"],
            primary["category_rows"],
            ",",
        ),
    )
    for name, fields, rows, delimiter in exports:
        path = output_dir / name
        atomic_write_csv(path, fields, rows, delimiter)
        output_files.append(path)

    status_rows = [
        {
            "instance_id": row["instance_id"],
            "status": row["status"],
            "replay_calls": row["replay_calls"],
            "expected_calls": row["expected_calls"],
            "replay_complete": "True",
        }
        for row in primary["status_rows"]
    ]
    status_path = output_dir / "golden_status.tsv"
    atomic_write_csv(
        status_path,
        ["instance_id", "status", "replay_calls", "expected_calls", "replay_complete"],
        status_rows,
        delimiter="\t",
    )
    output_files.append(status_path)

    phase_summary: list[dict[str, Any]] = []
    for field in PHASE_FIELDS:
        values = [
            number(row[field], field, series_dir / "round1" / "case_phases.csv")
            for row in primary["phase_rows"]
        ]
        phase_summary.append(
            {
                "metric": field,
                "cases": len(values),
                "total_ms": round(sum(values), 3),
                "mean_ms": round(sum(values) / len(values), 3),
                "median_ms": round(percentile(values, 0.5), 3),
                "p90_ms": round(percentile(values, 0.9), 3),
                "min_ms": round(min(values), 3),
                "max_ms": round(max(values), 3),
            }
        )
    phase_summary_path = output_dir / "golden_phase_summary.csv"
    atomic_write_csv(
        phase_summary_path,
        ["metric", "cases", "total_ms", "mean_ms", "median_ms", "p90_ms", "min_ms", "max_ms"],
        phase_summary,
    )
    output_files.append(phase_summary_path)

    full_wall = next(row for row in phase_summary if row["metric"] == "full_wall_ms")
    metadata = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "selection_rule": "round1_is_golden_round2_is_validation_only",
        "source_series": str(series_dir),
        "source_platform": primary["run_info"].get("host", ""),
        "cpu_set": primary["run_info"].get("swe_cpuset", ""),
        "case_timeout_seconds": primary["run_info"].get("case_timeout_seconds", ""),
        "case_count": args.expected_cases,
        "passed_cases": args.expected_cases,
        "tool_calls": args.expected_tool_calls,
        "full_wall_total_ms": full_wall["total_ms"],
        "full_wall_mean_ms": full_wall["mean_ms"],
        "secondary_validation": "PASS",
        "secondary_validation_case_count": args.expected_cases,
    }
    metadata_path = output_dir / "golden_metadata.json"
    atomic_write_text(metadata_path, json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
    output_files.append(metadata_path)

    summary = (
        "AWS36 单核 Golden 数据\n"
        "======================\n"
        "正式数据口径：第一轮作为 Golden；第二轮仅用于完整性复核，不参与平均。\n\n"
        f"平台：{metadata['source_platform']}\n"
        f"固定逻辑 CPU：{metadata['cpu_set']}\n"
        f"Case：{metadata['passed_cases']}/{metadata['case_count']} PASS\n"
        f"ToolCall：{metadata['tool_calls']}\n"
        f"Golden 全部 case 累计 wall time：{metadata['full_wall_total_ms']} ms\n"
        f"Golden 单 case 平均 wall time：{metadata['full_wall_mean_ms']} ms\n"
        f"第二轮复核：{metadata['secondary_validation']}\n"
    )
    summary_path = output_dir / "golden_summary.txt"
    atomic_write_text(summary_path, summary)
    output_files.append(summary_path)

    checksums_path = output_dir / "SHA256SUMS"
    checksum_lines = [f"{sha256(path)}  {path.name}" for path in sorted(output_files)]
    atomic_write_text(checksums_path, "\n".join(checksum_lines) + "\n")

    print("GOLDEN_EXPORT=PASS")
    print(f"SERIES_DIR={series_dir}")
    print(f"OUTPUT_DIR={output_dir}")
    print(f"CASES={args.expected_cases}")
    print(f"TOOL_CALLS={args.expected_tool_calls}")
    print("SECONDARY_VALIDATION=PASS")


if __name__ == "__main__":
    main()
