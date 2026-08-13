#!/usr/bin/env python3
"""Build a reproducible manifest for the selected AWS SWE-agent trajectories."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


EXTRA8 = {
    "django__django-12915",
    "sympy__sympy-22840",
    "sympy__sympy-11870",
    "sympy__sympy-20049",
    "sympy__sympy-12481",
    "sympy__sympy-12419",
    "sympy__sympy-22714",
    "sympy__sympy-20212",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def image_reference(instance_id: str) -> str:
    owner, project_and_number = instance_id.split("__", 1)
    return (
        "docker.io/swebench/sweb.eval.x86_64."
        f"{owner}_1776_{project_and_number}:latest"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trajectory-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--submission", required=True)
    args = parser.parse_args()

    cases = []
    for case_dir in sorted(path for path in args.trajectory_root.iterdir() if path.is_dir()):
        instance_id = case_dir.name
        trajectory_path = case_dir / f"{instance_id}.traj"
        config_path = case_dir / f"{instance_id}.config.yaml"
        prediction_path = case_dir / f"{instance_id}.pred"
        for required in (trajectory_path, config_path, prediction_path):
            if not required.is_file():
                raise SystemExit(f"Missing required file: {required}")

        trajectory = json.loads(trajectory_path.read_text(encoding="utf-8"))
        steps = trajectory.get("trajectory") or []
        files = []
        for path in sorted(case_dir.iterdir()):
            if not path.is_file() or path.name.endswith(".done"):
                continue
            files.append(
                {
                    "name": path.name,
                    "size_bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
            )
        cases.append(
            {
                "instance_id": instance_id,
                "group": "extra8" if instance_id in EXTRA8 else "base30",
                "image": image_reference(instance_id),
                "trajectory": str(trajectory_path.relative_to(args.trajectory_root)),
                "step_count": len(steps),
                "recorded_tool_seconds": round(
                    sum(float(step.get("execution_time") or 0) for step in steps), 6
                ),
                "files": files,
            }
        )

    case_ids = {case["instance_id"] for case in cases}
    missing_extra = EXTRA8 - case_ids
    if len(cases) != 38 or missing_extra:
        raise SystemExit(
            f"Expected 38 cases including all extra8; found={len(cases)} "
            f"missing_extra={sorted(missing_extra)}"
        )

    manifest = {
        "format_version": 1,
        "name": "swe-agent-aws38",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "submission": args.submission,
        "trajectory_format": "SWE-agent 1.0 trajectory",
        "summary": {
            "case_count": len(cases),
            "base30_count": sum(case["group"] == "base30" for case in cases),
            "extra8_count": sum(case["group"] == "extra8" for case in cases),
            "step_count": sum(case["step_count"] for case in cases),
            "recorded_tool_seconds": round(
                sum(case["recorded_tool_seconds"] for case in cases), 6
            ),
        },
        "cases": cases,
    }
    args.output.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
