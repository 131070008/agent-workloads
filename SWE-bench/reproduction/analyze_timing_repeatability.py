#!/usr/bin/env python3
"""Compare two timing passes per platform and select rerun candidates."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


def read(path: Path) -> dict[str, dict[str, str]]:
    with path.open() as handle:
        return {row["instance_id"]: row for row in csv.DictReader(handle)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--a-run1", type=Path, required=True)
    parser.add_argument("--a-run2", type=Path, required=True)
    parser.add_argument("--b-run1", type=Path, required=True)
    parser.add_argument("--b-run2", type=Path, required=True)
    parser.add_argument("--a-name", default="a")
    parser.add_argument("--b-name", default="b")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeat-low", type=float, default=0.85)
    parser.add_argument("--repeat-high", type=float, default=1.18)
    parser.add_argument("--cross-change", type=float, default=0.15)
    args = parser.parse_args()

    a1 = read(args.a_run1 / "case_phases.csv")
    a2 = read(args.a_run2 / "case_phases.csv")
    b1 = read(args.b_run1 / "case_phases.csv")
    b2 = read(args.b_run2 / "case_phases.csv")
    ids = sorted(set(a1) & set(a2) & set(b1) & set(b2))
    if len(ids) != 38:
        raise SystemExit(f"Expected 38 common cases, found {len(ids)}")

    rows = []
    for iid in ids:
        av1, av2 = float(a1[iid]["full_wall_ms"]), float(a2[iid]["full_wall_ms"])
        bv1, bv2 = float(b1[iid]["full_wall_ms"]), float(b2[iid]["full_wall_ms"])
        a_repeat = av2 / av1
        b_repeat = bv2 / bv1
        cross1 = bv1 / av1
        cross2 = bv2 / av2
        cross_delta = abs(cross2 / cross1 - 1.0)
        reasons = []
        if not args.repeat_low <= a_repeat <= args.repeat_high:
            reasons.append(f"{args.a_name}_repeat")
        if not args.repeat_low <= b_repeat <= args.repeat_high:
            reasons.append(f"{args.b_name}_repeat")
        if cross_delta > args.cross_change:
            reasons.append("cross_ratio_change")
        rows.append({
            "instance_id": iid,
            f"{args.a_name}_run1_ms": round(av1, 3),
            f"{args.a_name}_run2_ms": round(av2, 3),
            f"{args.a_name}_run2_over_run1": round(a_repeat, 5),
            f"{args.b_name}_run1_ms": round(bv1, 3),
            f"{args.b_name}_run2_ms": round(bv2, 3),
            f"{args.b_name}_run2_over_run1": round(b_repeat, 5),
            f"run1_{args.b_name}_over_{args.a_name}": round(cross1, 5),
            f"run2_{args.b_name}_over_{args.a_name}": round(cross2, 5),
            "cross_ratio_change_percent": round(cross_delta * 100.0, 3),
            "rerun": bool(reasons),
            "reasons": ";".join(reasons),
        })

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    selected = [row for row in rows if row["rerun"]]
    print(f"paired_cases={len(rows)} rerun_candidates={len(selected)}")
    for row in selected:
        print(row["instance_id"], row["reasons"], row["cross_ratio_change_percent"])


if __name__ == "__main__":
    main()
