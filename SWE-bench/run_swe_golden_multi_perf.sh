#!/usr/bin/env bash
set -euo pipefail

ROOT=/home/higon/cunzhe/agent-workloads
PYTHON=/home/higon/cunzhe/agent-workloads/.venv-swe/bin/python
GOLDEN_DIR=${SWE_GOLDEN_DIR:-/home/higon/cunzhe/swe_runs/golden_replay/flash}
WORKERS=${1:-8}
REPEATS=${2:-1}
CPUSET=${SWE_CPUSET:-0-7}
STAMP=$(date +%Y%m%d_%H%M%S)
OUTPUT_DIR=${SWE_OUTPUT_DIR:-/home/higon/cunzhe/swe_runs/golden_perf/multi_${WORKERS}w_${STAMP}}

test -x "$PYTHON"
test -f "$GOLDEN_DIR/manifest.json"
mkdir -p "$OUTPUT_DIR"
RUN_STARTED=$(date +%s.%N)
awk '$1 ~ /^cpu[0-7]$/ {print}' /proc/stat > "$OUTPUT_DIR/cpu_stat_start.txt"

set +e
"$PYTHON" "$ROOT/SWE-bench/run_swe_golden_replay.py" \
  --golden-dir "$GOLDEN_DIR" \
  --output-dir "$OUTPUT_DIR" \
  --workers "$WORKERS" \
  --repeats "$REPEATS" \
  --delay-scale 0 \
  --agent-cpuset "$CPUSET" \
  --sandbox-cpuset "$CPUSET" \
  --network-none \
  --validation-mode semantic \
  > "$OUTPUT_DIR/replay.stdout" 2>&1
RUNNER_RC=$?
set -e

awk '$1 ~ /^cpu[0-7]$/ {print}' /proc/stat > "$OUTPUT_DIR/cpu_stat_end.txt"
RUN_FINISHED=$(date +%s.%N)
"$PYTHON" -c 'import json,sys; s=float(sys.argv[1]); f=float(sys.argv[2]); print(json.dumps({"started_at":s,"finished_at":f,"elapsed_seconds":f-s},indent=2))' \
  "$RUN_STARTED" "$RUN_FINISHED" > "$OUTPUT_DIR/run_wall_clock.json"
"$PYTHON" "$ROOT/SWE-bench/summarize_swe_golden_perf.py" "$OUTPUT_DIR" \
  | tee "$OUTPUT_DIR/performance_summary.stdout"
echo "$RUNNER_RC" > "$OUTPUT_DIR/runner_returncode.txt"
echo "OUTPUT_DIR=$OUTPUT_DIR"
exit "$RUNNER_RC"
