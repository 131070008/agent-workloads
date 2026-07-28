#!/usr/bin/env bash
set -euo pipefail

ROOT=/home/higon/cunzhe/agent-workloads
PYTHON=/home/higon/cunzhe/agent-workloads/.venv-swe/bin/python
GOLDEN_DIR=${SWE_GOLDEN_DIR:-/home/higon/cunzhe/swe_runs/golden_replay/flash}
WORKERS=${1:-8}
WARMUP_SECONDS=${2:-60}
MEASURE_SECONDS=${3:-300}
CPUSET=${SWE_CPUSET:-0-7}
STAMP=$(date +%Y%m%d_%H%M%S)
OUTPUT_DIR=${SWE_OUTPUT_DIR:-/home/higon/cunzhe/swe_runs/golden_rate/rate_${WORKERS}w_${STAMP}}

test -x "$PYTHON"
test -f "$GOLDEN_DIR/manifest.json"
mkdir -p "$OUTPUT_DIR"

taskset -c "$CPUSET" "$PYTHON" "$ROOT/SWE-bench/run_swe_golden_rate.py" \
  --golden-dir "$GOLDEN_DIR" \
  --output-dir "$OUTPUT_DIR" \
  --workers "$WORKERS" \
  --warmup-seconds "$WARMUP_SECONDS" \
  --measure-seconds "$MEASURE_SECONDS" \
  --agent-cpuset "$CPUSET" \
  --sandbox-cpuset "$CPUSET" \
  | tee "$OUTPUT_DIR/rate.stdout"
