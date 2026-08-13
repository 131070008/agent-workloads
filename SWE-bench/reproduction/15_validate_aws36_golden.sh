#!/usr/bin/env bash
set -euo pipefail

DATA_ROOT=${DATA_ROOT:-/data/cunzhe}
REPO_ROOT=${REPO_ROOT:-$DATA_ROOT/agent-workloads}
RUNTIME_ROOT=${RUNTIME_ROOT:-$DATA_ROOT}
SUBMISSION=${AWS_SUBMISSION:-20250226_sweagent_claude-3-7-sonnet-20250219}
TRAJECTORY_ROOT=${TRAJECTORY_ROOT:-$DATA_ROOT/swe_runs/aws_public_traces/$SUBMISSION}
MANIFEST=${AWS38_MANIFEST:-$TRAJECTORY_ROOT/aws38_manifest.json}
SWEAGENT_SOURCE=${SWEAGENT_SOURCE:-$RUNTIME_ROOT/swe-agent-v1.0.0-src}
SWEAGENT_VENV=${SWEAGENT_VENV:-$RUNTIME_ROOT/sweagent-v1.0.0-venv}
SHARED_REX=${SHARED_REX:-$RUNTIME_ROOT/swerex-runtime-1.1.0-shared}
TOOL_WHEELHOUSE=${TOOL_WHEELHOUSE:-$RUNTIME_ROOT/swe-tool-wheelhouse-v1.0.0}
REPRO_DIR=$REPO_ROOT/SWE-bench/reproduction
EXCLUDE_FILE=$REPRO_DIR/golden36_excluded_cases.txt

required_files=(
  "$MANIFEST"
  "$EXCLUDE_FILE"
  "$REPRO_DIR/10_run_aws38_replay_case.sh"
  "$REPRO_DIR/14_run_aws38_timed_full.sh"
  "$REPRO_DIR/16_run_aws36_golden.sh"
  "$REPRO_DIR/lifecycle_timing_probe.py"
  "$REPRO_DIR/edit_anthropic_install_offline.sh"
)
required_dirs=(
  "$SWEAGENT_SOURCE/tools"
  "$SWEAGENT_VENV"
  "$SHARED_REX"
  "$TOOL_WHEELHOUSE"
)

for path in "${required_files[@]}"; do
  [[ -f "$path" ]] || { echo "MISSING_FILE $path" >&2; exit 1; }
done
for path in "${required_dirs[@]}"; do
  [[ -d "$path" ]] || { echo "MISSING_DIR $path" >&2; exit 1; }
done

test -x "$SWEAGENT_VENV/bin/python"
test -x "$SHARED_REX/bin/swerex-remote"
command -v docker >/dev/null
docker info >/dev/null

DATA_ROOT="$DATA_ROOT" \
TRAJECTORY_ROOT="$TRAJECTORY_ROOT" \
MANIFEST="$MANIFEST" \
EXCLUDE_FILE="$EXCLUDE_FILE" \
python3 - <<'PY'
import json
import os
import subprocess
from pathlib import Path

manifest = json.load(open(os.environ["MANIFEST"]))
trajectory_root = Path(os.environ["TRAJECTORY_ROOT"])
excluded = {
    line.strip()
    for line in Path(os.environ["EXCLUDE_FILE"]).read_text().splitlines()
    if line.strip() and not line.startswith("#")
}
cases = [case for case in manifest["cases"] if case["instance_id"] not in excluded]
if len(manifest["cases"]) != 38 or len(cases) != 36:
    raise SystemExit(f"Expected AWS38/Golden36, got {len(manifest['cases'])}/{len(cases)}")

missing_trajectories = []
missing_images = []
for case in cases:
    trajectory = trajectory_root / case["trajectory"]
    if not trajectory.is_file():
        missing_trajectories.append(str(trajectory))
        continue
    data = json.loads(trajectory.read_text())
    config = data["replay_config"]
    if isinstance(config, str):
        config = json.loads(config)
    image = config["env"]["deployment"]["image"].removeprefix("docker.io/")
    result = subprocess.run(
        ["docker", "image", "inspect", image],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if result.returncode:
        missing_images.append(image)

if missing_trajectories:
    print("MISSING_TRAJECTORIES")
    print("\n".join(missing_trajectories))
if missing_images:
    print("MISSING_IMAGES")
    print("\n".join(missing_images))
if missing_trajectories or missing_images:
    raise SystemExit(1)

print("GOLDEN36_CASES=36")
print("GOLDEN36_TRAJECTORIES=36")
print("GOLDEN36_IMAGES=36")
print("EXCLUDED=" + ",".join(sorted(excluded)))
PY

echo "SWEAGENT_SOURCE=$SWEAGENT_SOURCE"
echo "SWEAGENT_VENV=$SWEAGENT_VENV"
echo "SHARED_REX=$SHARED_REX"
echo "TOOL_WHEELHOUSE=$TOOL_WHEELHOUSE"
echo "VALIDATION=PASS"
