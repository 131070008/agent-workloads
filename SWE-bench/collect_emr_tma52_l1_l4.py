#!/usr/bin/env python3
"""Collect the official Intel EMR TMA 5.2 L1-L4 event set without multiplexing."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path


ERROR_PATTERNS = (
    "<not counted>",
    "<not supported>",
    "No permission",
    "Access to performance",
    "event syntax error",
    "failed to parse event",
)

FIXED_ORDER = (
    "TOPDOWN.SLOTS",
    "PERF_METRICS.RETIRING",
    "PERF_METRICS.BAD_SPECULATION",
    "PERF_METRICS.FRONTEND_BOUND",
    "PERF_METRICS.BACKEND_BOUND",
    "PERF_METRICS.BRANCH_MISPREDICTS",
    "PERF_METRICS.MEMORY_BOUND",
    "PERF_METRICS.HEAVY_OPERATIONS",
    "PERF_METRICS.FETCH_LATENCY",
)

ARCH_FIXED = {
    "CPU_CLK_UNHALTED.THREAD",
    "CPU_CLK_UNHALTED.REF_TSC",
    "INST_RETIRED.ANY",
}


@dataclass(frozen=True)
class Event:
    intel_name: str
    perf_syntax: str
    counter: str
    taken_alone: bool
    offcore: bool

    @property
    def restricted(self) -> bool:
        return self.counter == "0,1,2,3"

    @property
    def perf_name(self) -> str:
        token = re.sub(r"[^a-z0-9]+", "_", self.intel_name.lower()).strip("_")
        return f"emr_{token}"

    @property
    def named_syntax(self) -> str:
        if not self.perf_syntax.startswith("cpu/"):
            return self.perf_syntax
        return self.perf_syntax[:-1] + f",name={self.perf_name}/"


@dataclass
class Pass:
    name: str
    kind: str
    events: list[Event]
    expression: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--cpuset", default="0-7")
    parser.add_argument("--cgroups", required=True)
    parser.add_argument("--cgroup-seconds", type=int, default=5)
    parser.add_argument("--global-seconds", type=int, default=3)
    parser.add_argument("--validation-seconds", type=float, default=0.25)
    parser.add_argument("--validate-only", action="store_true")
    return parser.parse_args()


def load_events(path: Path) -> tuple[dict, list[Event]]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    events = []
    for item in manifest["events"]:
        if "error" in item:
            raise ValueError(f"{item['name']}: {item['error']}")
        events.append(
            Event(
                intel_name=item["name"],
                perf_syntax=item["perf_syntax"],
                counter=item["counter"],
                taken_alone=item["taken_alone"] == "1",
                offcore=item["offcore"] == "1",
            )
        )
    return manifest, events


def base_name(event: Event) -> str:
    return event.intel_name.split(":", 1)[0]


def fixed_expression(events: list[Event]) -> tuple[str, list[Event]]:
    by_base = {base_name(event): event for event in events}
    fixed = [by_base[name] for name in FIXED_ORDER]
    uop_dropping = by_base["INT_MISC.UOP_DROPPING"]
    group = "{" + ",".join(event.perf_syntax for event in fixed) + "}"
    return f"{group},{uop_dropping.named_syntax}", fixed + [uop_dropping]


def general_expression(events: list[Event]) -> str:
    raw = ",".join(event.named_syntax for event in events)
    if len(events) > 1:
        raw = "{" + raw + "}"
    return f"cycles,ref-cycles,instructions,{raw}"


def build_passes(events: list[Event]) -> list[Pass]:
    fixed_expr, fixed_events = fixed_expression(events)
    excluded = {event.intel_name for event in fixed_events}
    excluded.update(ARCH_FIXED)
    programmable = [event for event in events if event.intel_name not in excluded]

    taken_alone = [event for event in programmable if event.taken_alone]
    offcore = [
        event
        for event in programmable
        if event.offcore and not event.taken_alone
    ]
    regular = [
        event
        for event in programmable
        if not event.taken_alone and not event.offcore
    ]

    groups: list[list[Event]] = []
    for event in sorted(
        regular,
        key=lambda item: (not item.restricted, item.intel_name),
    ):
        for group in groups:
            restricted_count = sum(item.restricted for item in group)
            if len(group) >= 8:
                continue
            if event.restricted and restricted_count >= 4:
                continue
            if not event.restricted and len(group) - restricted_count >= 8:
                continue
            group.append(event)
            break
        else:
            groups.append([event])

    passes = [
        Pass(
            name="00_fixed_perf_metrics",
            kind="fixed_perf_metrics",
            events=fixed_events,
            expression=fixed_expr,
        )
    ]
    for index, group in enumerate(groups, start=1):
        passes.append(
            Pass(
                name=f"{index:02d}_programmable",
                kind="programmable",
                events=group,
                expression=general_expression(group),
            )
        )
    offset = len(passes)
    for index, event in enumerate(taken_alone, start=offset):
        passes.append(
            Pass(
                name=f"{index:02d}_taken_alone",
                kind="taken_alone",
                events=[event],
                expression=general_expression([event]),
            )
        )
    offset = len(passes)
    for index, event in enumerate(offcore, start=offset):
        passes.append(
            Pass(
                name=f"{index:02d}_offcore",
                kind="offcore",
                events=[event],
                expression=general_expression([event]),
            )
        )
    return passes


def run_command(command: list[str]) -> tuple[int, str, float]:
    started = time.monotonic()
    result = subprocess.run(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    return result.returncode, result.stdout, time.monotonic() - started


def output_has_error(output: str) -> bool:
    return any(pattern in output for pattern in ERROR_PATTERNS)


def collection_has_error(output: str, scope: str) -> bool:
    if any(
        pattern in output
        for pattern in ERROR_PATTERNS
        if pattern != "<not counted>"
    ):
        return True
    runtime_index = 5 if scope == "cgroup" else 4
    for row in csv.reader(output.splitlines()):
        if len(row) <= runtime_index or row[1] != "<not counted>":
            continue
        try:
            runtime = float(row[runtime_index])
        except ValueError:
            return True
        if runtime != 0:
            return True
    return False


def running_percentages(output: str, scope: str) -> list[float]:
    percentages = []
    index = 6 if scope == "cgroup" else 5
    for row in csv.reader(output.splitlines()):
        if not row or not row[0].startswith("CPU") or len(row) <= index:
            continue
        try:
            percentages.append(float(row[index]))
        except ValueError:
            continue
    return percentages


def validate_passes(
    passes: list[Pass],
    first_cpu: str,
    seconds: float,
    output_dir: Path,
) -> None:
    validation_dir = output_dir / "validation"
    validation_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for item in passes:
        command = [
            "perf",
            "stat",
            "-a",
            "-C",
            first_cpu,
            "-A",
            "-x,",
            "-e",
            item.expression,
            "--",
            "sleep",
            str(seconds),
        ]
        returncode, output, elapsed = run_command(command)
        (validation_dir / f"{item.name}.txt").write_text(
            "$ " + " ".join(command) + "\n" + output,
            encoding="utf-8",
        )
        percentages = running_percentages(output, "global")
        valid = (
            returncode == 0
            and not output_has_error(output)
            and bool(percentages)
            and min(percentages) >= 99.0
        )
        rows.append(
            {
                "pass": item.name,
                "kind": item.kind,
                "events": len(item.events),
                "returncode": returncode,
                "elapsed_seconds": f"{elapsed:.6f}",
                "valid": int(valid),
                "running_percent_min": (
                    f"{min(percentages):.2f}" if percentages else "NA"
                ),
                "running_percent_max": (
                    f"{max(percentages):.2f}" if percentages else "NA"
                ),
            }
        )
        if not valid:
            raise RuntimeError(
                f"PMU pass validation failed: {item.name}; "
                f"see {validation_dir / (item.name + '.txt')}"
            )
    write_csv(output_dir / "validation_summary.csv", rows)


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_plan(
    output_dir: Path,
    manifest: dict,
    events: list[Event],
    passes: list[Pass],
    args: argparse.Namespace,
) -> None:
    covered = {event.intel_name for item in passes for event in item.events}
    expected = {event.intel_name for event in events}
    covered.update(ARCH_FIXED & expected)
    if covered != expected:
        missing = sorted(expected - covered)
        extra = sorted(covered - expected)
        raise ValueError(f"event coverage mismatch: missing={missing}, extra={extra}")

    plan = {
        "source": manifest["source"],
        "cpuset": args.cpuset,
        "cgroups": args.cgroups.split(","),
        "cgroup_seconds": args.cgroup_seconds,
        "global_seconds": args.global_seconds,
        "unique_event_count": len(events),
        "pass_count": len(passes),
        "passes": [
            {
                "name": item.name,
                "kind": item.kind,
                "expression": item.expression,
                "events": [event.intel_name for event in item.events],
            }
            for item in passes
        ],
    }
    (output_dir / "collection_plan.json").write_text(
        json.dumps(plan, indent=2) + "\n",
        encoding="utf-8",
    )
    rows = []
    for item in passes:
        for event in item.events:
            rows.append(
                {
                    "pass": item.name,
                    "kind": item.kind,
                    "intel_event": event.intel_name,
                    "perf_name": event.perf_name,
                    "perf_syntax": event.perf_syntax,
                    "counter": event.counter,
                    "taken_alone": int(event.taken_alone),
                    "offcore": int(event.offcore),
                }
            )
    for name in sorted(ARCH_FIXED):
        event = next(
            (item for item in events if item.intel_name == name),
            None,
        )
        if event is None:
            continue
        rows.append(
            {
                "pass": "all_programmable_passes",
                "kind": "architectural_fixed",
                "intel_event": event.intel_name,
                "perf_name": event.perf_syntax,
                "perf_syntax": event.perf_syntax,
                "counter": event.counter,
                "taken_alone": 0,
                "offcore": 0,
            }
        )
    write_csv(output_dir / "event_to_pass.csv", rows)


def collect_scope(
    item: Pass,
    scope: str,
    seconds: int,
    args: argparse.Namespace,
    output_dir: Path,
) -> dict:
    command = [
        "perf",
        "stat",
        "-a",
        "-C",
        args.cpuset,
        "-A",
        "-x,",
        "-e",
        item.expression,
    ]
    if scope == "cgroup":
        command += ["--for-each-cgroup", args.cgroups]
    command += ["--", "sleep", str(seconds)]

    returncode, output, elapsed = run_command(command)
    target = output_dir / f"raw_{scope}" / f"{item.name}.csv"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "# command=" + " ".join(command) + "\n" + output,
        encoding="utf-8",
    )
    percentages = running_percentages(output, scope)
    valid = (
        returncode == 0
        and not collection_has_error(output, scope)
        and bool(percentages)
        and min(percentages) >= 99.0
    )
    if not valid:
        raise RuntimeError(f"{scope} collection failed: {item.name}; see {target}")
    return {
        "pass": item.name,
        "kind": item.kind,
        "scope": scope,
        "events": len(item.events),
        "requested_seconds": seconds,
        "elapsed_seconds": f"{elapsed:.6f}",
        "returncode": returncode,
        "valid": int(valid),
        "running_percent_min": f"{min(percentages):.2f}",
        "running_percent_max": f"{max(percentages):.2f}",
        "output": str(target),
    }


def main() -> None:
    args = parse_args()
    if os.geteuid() != 0:
        raise SystemExit("Run this collector as root so perf can use system-wide cgroups.")
    if args.cgroup_seconds <= 0 or args.global_seconds <= 0:
        raise SystemExit("Collection durations must be positive.")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest, events = load_events(args.manifest)
    passes = build_passes(events)
    write_plan(args.output_dir, manifest, events, passes, args)
    first_cpu = re.split(r"[-,]", args.cpuset, maxsplit=1)[0]
    validate_passes(
        passes,
        first_cpu,
        args.validation_seconds,
        args.output_dir,
    )

    if args.validate_only:
        print(
            f"Validated {len(events)} EMR events in {len(passes)} "
            f"non-multiplexed passes."
        )
        return

    rows = []
    for item in passes:
        rows.append(
            collect_scope(
                item,
                "cgroup",
                args.cgroup_seconds,
                args,
                args.output_dir,
            )
        )
        rows.append(
            collect_scope(
                item,
                "global",
                args.global_seconds,
                args,
                args.output_dir,
            )
        )
    write_csv(args.output_dir / "collection_summary.csv", rows)

    result = {
        "completed_at_epoch": time.time(),
        "unique_event_count": len(events),
        "pass_count": len(passes),
        "scope_count": 2,
        "successful_collections": len(rows),
        "expected_collections": len(passes) * 2,
        "status": "complete",
    }
    (args.output_dir / "result.json").write_text(
        json.dumps(result, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise
