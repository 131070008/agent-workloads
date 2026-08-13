#!/usr/bin/env bash
set -euo pipefail

INSTANCE_ID=${1:-sympy__sympy-11870}
CUNZHE_ROOT=${CUNZHE_ROOT:-/home/higon/cunzhe}
RUNNER=${RUNNER:-$CUNZHE_ROOT/10_run_aws38_replay_case.sh}
OUTPUT_ROOT=${OUTPUT_ROOT:-$CUNZHE_ROOT/swe_runs/timing_doublecheck}
PROBE=${SWE_TIMING_PROBE:-$CUNZHE_ROOT/lifecycle_timing_probe.py}
STAMP=$(date +%Y%m%d_%H%M%S)
RUN_ROOT=$OUTPUT_ROOT/${INSTANCE_ID}_$STAMP

mkdir -p "$RUN_ROOT"

for iteration in 1 2; do
  iteration_root=$RUN_ROOT/run$iteration
  mkdir -p "$iteration_root"
  echo "[$(date -Is)] run=$iteration instance=$INSTANCE_ID"
  SWE_TIMING_PROBE="$PROBE" \
  OUTPUT_ROOT="$iteration_root" \
    "$RUNNER" "$INSTANCE_ID" | tee "$iteration_root/runner_summary.log"

  replay_dir=$(cat "$iteration_root/LATEST")
  test -f "$replay_dir/timing_summary.json"
  REPLAY_DIR="$replay_dir" python3 - <<'PY'
import csv
import json
import os
from pathlib import Path

root = Path(os.environ["REPLAY_DIR"])
trajectory = next(root.glob("*.local.traj"))
data = json.loads(trajectory.read_text())
expected = sum(
    item.get("role") == "assistant" and bool(item.get("tool_calls"))
    for item in data["history"]
)
summary_path = root / "timing_summary.json"
summary = json.loads(summary_path.read_text())
summary["expected_replay_calls"] = expected
calls = list(csv.DictReader((root / "tool_calls.csv").open()))
extra = calls[expected:]
summary["autosubmit_calls"] = len(extra)
summary["replay_complete"] = (
    len(calls) >= expected
    and all(call["category"] == "submission" for call in extra)
)
summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
PY
  cp "$replay_dir/timing_summary.json" "$RUN_ROOT/run${iteration}_timing_summary.json"
  cp "$replay_dir/tool_calls.csv" "$RUN_ROOT/run${iteration}_tool_calls.csv"
  cp "$replay_dir/category_summary.csv" "$RUN_ROOT/run${iteration}_category_summary.csv"
done

python3 - "$RUN_ROOT" <<'PY'
import csv
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
rows = []
for iteration in (1, 2):
    data = json.loads((root / f"run{iteration}_timing_summary.json").read_text())
    data = {"run": iteration, **data}
    rows.append(data)

fields = list(rows[0])
with (root / "doublecheck_summary.csv").open("w", newline="") as handle:
    writer = csv.DictWriter(handle, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)

print("\nDouble-check summary (milliseconds):")
show = [
    "full_wall_ms", "environment_start_ms", "agent_setup_ms", "step_total_ms",
    "tool_and_submission_ms", "communicate_ms", "environment_close_ms", "tool_calls",
    "expected_replay_calls", "autosubmit_calls", "replay_complete",
]
print("run\t" + "\t".join(show))
for row in rows:
    print(str(row["run"]) + "\t" + "\t".join(str(row[key]) for key in show))
print(f"\nResults: {root}")
PY
