#!/usr/bin/env python3
"""Validate every raw event in an EMR Top-down manifest with perf stat."""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--duration", type=float, default=0.02)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def validate_event(perf_syntax: str, duration: float) -> tuple[str, str, str]:
    command = [
        "perf",
        "stat",
        "-x,",
        "-e",
        perf_syntax,
        "--",
        "sleep",
        str(duration),
    ]
    result = subprocess.run(
        command,
        text=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        check=False,
    )
    output = result.stderr.replace("\n", " ").strip()
    bad_markers = (
        "<not supported>",
        "<not counted>",
        "event syntax error",
        "No permission",
        "Access to performance monitoring",
    )
    status = "ok"
    if result.returncode != 0 or any(marker in output for marker in bad_markers):
        status = "failed"
    return status, str(result.returncode), output


def main() -> None:
    args = parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    rows = []
    fixed_metric_events = [
        event
        for event in manifest["events"]
        if event.get("counter") == "fixed PERF_METRICS"
    ]
    fixed_metric_events.sort(
        key=lambda event: (event["base_name"] != "TOPDOWN.SLOTS", event["name"])
    )
    fixed_metric_result = None
    if fixed_metric_events:
        group = "{" + ",".join(
            event["perf_syntax"] for event in fixed_metric_events
        ) + "}"
        fixed_metric_result = validate_event(group, args.duration)

    for event in manifest["events"]:
        if "error" in event:
            rows.append(
                {
                    "event": event["name"],
                    "perf_syntax": "",
                    "status": "manifest_error",
                    "returncode": "",
                    "perf_output": event["error"],
                }
            )
            continue
        if event.get("counter") == "fixed PERF_METRICS":
            assert fixed_metric_result is not None
            status, returncode, output = fixed_metric_result
        else:
            status, returncode, output = validate_event(
                event["perf_syntax"], args.duration
            )
        rows.append(
            {
                "event": event["name"],
                "perf_syntax": event["perf_syntax"],
                "status": status,
                "returncode": returncode,
                "perf_output": output,
            }
        )

    fields = ["event", "perf_syntax", "status", "returncode", "perf_output"]
    if args.output:
        stream = args.output.open("w", encoding="utf-8", newline="")
    else:
        stream = sys.stdout
    try:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    finally:
        if args.output:
            stream.close()

    failures = sum(row["status"] != "ok" for row in rows)
    print(
        f"validated={len(rows)} failures={failures}",
        file=sys.stderr,
    )
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
