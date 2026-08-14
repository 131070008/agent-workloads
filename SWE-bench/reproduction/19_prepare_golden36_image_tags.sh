#!/usr/bin/env bash
set -euo pipefail

DATA_ROOT=${DATA_ROOT:-/data/cunzhe}
REPO_ROOT=${REPO_ROOT:-$DATA_ROOT/agent-workloads}
SUBMISSION=${AWS_SUBMISSION:-20250226_sweagent_claude-3-7-sonnet-20250219}
TRAJECTORY_ROOT=${TRAJECTORY_ROOT:-$DATA_ROOT/swe_runs/aws_public_traces/$SUBMISSION}
MANIFEST=${AWS38_MANIFEST:-$TRAJECTORY_ROOT/aws38_manifest.json}
EXCLUDE_FILE=${EXCLUDE_FILE:-$REPO_ROOT/SWE-bench/reproduction/golden36_excluded_cases.txt}

test -f "$MANIFEST"
test -f "$EXCLUDE_FILE"
command -v docker >/dev/null
docker info >/dev/null

total=0
existing=0
tagged=0
missing=0

while IFS=$'\t' read -r source target; do
  total=$((total + 1))
  if docker image inspect "$target" >/dev/null 2>&1; then
    echo "EXISTS $target"
    existing=$((existing + 1))
    continue
  fi
  if ! docker image inspect "$source" >/dev/null 2>&1; then
    echo "MISSING source=$source target=$target" >&2
    missing=$((missing + 1))
    continue
  fi
  docker tag "$source" "$target"
  echo "TAGGED $source -> $target"
  tagged=$((tagged + 1))
done < <(
  MANIFEST="$MANIFEST" EXCLUDE_FILE="$EXCLUDE_FILE" TRAJECTORY_ROOT="$TRAJECTORY_ROOT" \
    python3 - <<'PY'
import json
import os
from pathlib import Path

manifest = json.load(open(os.environ["MANIFEST"]))
trajectory_root = Path(os.environ["TRAJECTORY_ROOT"])
excluded = {
    line.strip()
    for line in Path(os.environ["EXCLUDE_FILE"]).read_text().splitlines()
    if line.strip() and not line.startswith("#")
}

for case in manifest["cases"]:
    if case["instance_id"] in excluded:
        continue
    trajectory = json.loads((trajectory_root / case["trajectory"]).read_text())
    config = trajectory["replay_config"]
    if isinstance(config, str):
        config = json.loads(config)
    target = config["env"]["deployment"]["image"].removeprefix("docker.io/")
    name, separator, _tag = target.rpartition(":")
    if not separator:
        name = target
    source = f"{name}:latest"
    print(f"{source}\t{target}")
PY
)

echo "GOLDEN36_IMAGE_TAGS total=$total existing=$existing tagged=$tagged missing=$missing"
test "$total" -eq 36
test "$missing" -eq 0

