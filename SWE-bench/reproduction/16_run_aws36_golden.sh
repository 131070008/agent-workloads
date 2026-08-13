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
SWE_CPUSET=${SWE_CPUSET:-}
CASE_IDS=${CASE_IDS:-}
REPRO_DIR=$REPO_ROOT/SWE-bench/reproduction
TIMESTAMP=${TIMESTAMP:-$(date +%Y%m%d_%H%M%S)}
RUN_DIR=${RUN_DIR:-$DATA_ROOT/swe_runs/aws36_golden_$(hostname -s)_$TIMESTAMP}

DATA_ROOT="$DATA_ROOT" REPO_ROOT="$REPO_ROOT" RUNTIME_ROOT="$RUNTIME_ROOT" \
TRAJECTORY_ROOT="$TRAJECTORY_ROOT" AWS38_MANIFEST="$MANIFEST" \
SWEAGENT_SOURCE="$SWEAGENT_SOURCE" SWEAGENT_VENV="$SWEAGENT_VENV" \
SHARED_REX="$SHARED_REX" TOOL_WHEELHOUSE="$TOOL_WHEELHOUSE" \
  "$REPRO_DIR/15_validate_aws36_golden.sh"

# Tool installers are sourced into SWE-ReX's long-lived shell. This version
# deliberately does not leak `set -e` into subsequent ToolCalls.
cp "$REPRO_DIR/edit_anthropic_install_offline.sh" \
  "$SWEAGENT_SOURCE/tools/edit_anthropic/install.sh"
chmod +x "$SWEAGENT_SOURCE/tools/edit_anthropic/install.sh"

if [[ -z "$CASE_IDS" ]]; then
  CASE_IDS=$(MANIFEST="$MANIFEST" EXCLUDE_FILE="$REPRO_DIR/golden36_excluded_cases.txt" python3 - <<'PY'
import json
import os
from pathlib import Path

excluded = {
    line.strip()
    for line in Path(os.environ["EXCLUDE_FILE"]).read_text().splitlines()
    if line.strip() and not line.startswith("#")
}
manifest = json.load(open(os.environ["MANIFEST"]))
print(" ".join(case["instance_id"] for case in manifest["cases"] if case["instance_id"] not in excluded))
PY
  )
fi
case_count=$(wc -w <<< "$CASE_IDS")

echo "RUN_DIR=$RUN_DIR"
echo "CASE_COUNT=$case_count"
echo "SWE_CPUSET=${SWE_CPUSET:-unrestricted}"

CUNZHE_ROOT="$DATA_ROOT" \
RUNNER="$REPRO_DIR/10_run_aws38_replay_case.sh" \
SWE_TIMING_PROBE="$REPRO_DIR/lifecycle_timing_probe.py" \
AWS38_MANIFEST="$MANIFEST" \
TRAJECTORY_ROOT="$TRAJECTORY_ROOT" \
SWEAGENT_SOURCE="$SWEAGENT_SOURCE" \
SWEAGENT_VENV="$SWEAGENT_VENV" \
SHARED_REX="$SHARED_REX" \
TOOL_WHEELHOUSE="$TOOL_WHEELHOUSE" \
SWE_CPUSET="$SWE_CPUSET" \
RUN_DIR="$RUN_DIR" \
CASE_IDS="$CASE_IDS" \
  "$REPRO_DIR/14_run_aws38_timed_full.sh"

echo "GOLDEN36_COMPLETE=$RUN_DIR"
