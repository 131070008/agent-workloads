#!/usr/bin/env python3
"""Evaluate recorded Golden trajectories with the official SWE-bench harness."""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from datasets import Dataset


def read_cases(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream, delimiter="\t"))


def find_latest(roots: list[Path], instance_id: str) -> Path | None:
    candidates = []
    for root in roots:
        for path in root.glob(f"**/{instance_id}.traj.json"):
            try:
                if (read_json(path).get("info") or {}).get("exit_status"):
                    candidates.append(path)
            except Exception:
                continue
    return max(candidates, key=lambda path: path.stat().st_mtime) if candidates else None


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def find_report(report_dir: Path) -> Path | None:
    reports = []
    for path in report_dir.rglob("*.json"):
        try:
            obj = read_json(path)
        except Exception:
            continue
        if "resolved_instances" in obj and "submitted_instances" in obj:
            reports.append(path)
    return max(reports, key=lambda path: path.stat().st_mtime) if reports else None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selected-tsv", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, action="append", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--arrow", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    selected_tsv = args.selected_tsv.expanduser().resolve()
    roots = [root.expanduser().resolve() for root in args.source_root]
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    rows = read_cases(selected_tsv)
    dataset = Dataset.from_file(str(args.arrow.expanduser().resolve()))
    dataset_map = {dict(row)["instance_id"]: dict(row) for row in dataset}
    selected_dataset = []
    predictions = {}
    missing = []
    for row in rows:
        instance_id = row["instance_id"]
        trajectory_path = find_latest(roots, instance_id)
        if not trajectory_path:
            missing.append(instance_id)
            continue
        trajectory = read_json(trajectory_path)
        info = trajectory.get("info") or {}
        model_name = (info.get("config") or {}).get("model", {}).get("model_name", "recorded")
        predictions[instance_id] = {
            "model_name_or_path": model_name,
            "instance_id": instance_id,
            "model_patch": info.get("submission") or "",
        }
        selected_dataset.append(dataset_map[instance_id])

    dataset_path = output_dir / "dataset.json"
    predictions_path = output_dir / "preds.json"
    dataset_path.write_text(json.dumps(selected_dataset, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    predictions_path.write_text(json.dumps(predictions, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    prep = {
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "selected": len(rows),
        "prepared": len(predictions),
        "missing": missing,
        "dataset": str(dataset_path),
        "predictions": str(predictions_path),
    }
    (output_dir / "evaluation_input.json").write_text(
        json.dumps(prep, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(prep, ensure_ascii=False, indent=2), flush=True)
    if missing:
        raise SystemExit(2)
    if args.prepare_only:
        return

    report_dir = output_dir / "report"
    command = [
        os.path.abspath(str(args.python.expanduser())),
        "-m",
        "swebench.harness.run_evaluation",
        "--dataset_name",
        str(dataset_path),
        "--split",
        "test",
        "--instance_ids",
        *[row["instance_id"] for row in rows],
        "--predictions_path",
        str(predictions_path),
        "--max_workers",
        str(args.workers),
        "--timeout",
        str(args.timeout),
        "--run_id",
        args.run_id,
        "--namespace",
        "swebench",
        "--cache_level",
        "env",
        "--clean",
        "false",
        "--report_dir",
        str(report_dir),
    ]
    with (output_dir / "evaluator.log").open("w", encoding="utf-8", errors="replace") as log:
        completed = subprocess.run(
            command,
            cwd=str(output_dir),
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
    # SWE-bench 4.1 may write the aggregate JSON in cwd even when report_dir is
    # provided, while other releases place it below report_dir.
    report = find_report(output_dir)
    summary = {
        "returncode": completed.returncode,
        "report": str(report) if report else None,
        "result": read_json(report) if report else None,
    }
    (output_dir / "evaluation_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    if completed.returncode != 0 or report is None:
        raise SystemExit(3)


if __name__ == "__main__":
    main()
