#!/usr/bin/env bash
set -euo pipefail

ROOT=/home/higon/cunzhe/agent-workloads
PYTHON=/home/higon/cunzhe/agent-workloads/.venv-swe/bin/python
GOLDEN_DIR=${SWE_GOLDEN_DIR:-/home/higon/cunzhe/swe_runs/golden_replay/flash}
INSTANCE_ID=${1:-pytest-dev__pytest-11148}
REPEATS=${2:-3}
CPUSET=${SWE_CPUSET:-0-7}
STAMP=$(date +%Y%m%d_%H%M%S)
OUTPUT_DIR=${SWE_OUTPUT_DIR:-/home/higon/cunzhe/swe_runs/golden_perf/single_${INSTANCE_ID//[^A-Za-z0-9_.-]/_}_${STAMP}}
TRAJECTORY="$GOLDEN_DIR/trajectories/$INSTANCE_ID.traj.json"

test -x "$PYTHON"
test -f "$TRAJECTORY"
mkdir -p "$OUTPUT_DIR"
RUN_STARTED=$(date +%s.%N)
awk '$1 ~ /^cpu[0-7]$/ {print}' /proc/stat > "$OUTPUT_DIR/cpu_stat_start.txt"

for repeat in $(seq 1 "$REPEATS"); do
  RUN_DIR="$OUTPUT_DIR/repeat_$(printf '%02d' "$repeat")"
  taskset -c "$CPUSET" "$PYTHON" \
    "$ROOT/SWE-bench/replay_swe_trajectory.py" \
    --trajectory "$TRAJECTORY" \
    --output-dir "$RUN_DIR" \
    --cpuset "$CPUSET" \
    --delay-scale 0 \
    --network-none \
    --container-memory 16g \
    --container-pids-limit 4096 \
    > "$RUN_DIR.log" 2>&1
done

awk '$1 ~ /^cpu[0-7]$/ {print}' /proc/stat > "$OUTPUT_DIR/cpu_stat_end.txt"
RUN_FINISHED=$(date +%s.%N)
"$PYTHON" -c 'import json,sys; s=float(sys.argv[1]); f=float(sys.argv[2]); print(json.dumps({"started_at":s,"finished_at":f,"elapsed_seconds":f-s},indent=2))' \
  "$RUN_STARTED" "$RUN_FINISHED" > "$OUTPUT_DIR/run_wall_clock.json"
"$PYTHON" "$ROOT/SWE-bench/summarize_swe_golden_perf.py" "$OUTPUT_DIR" \
  | tee "$OUTPUT_DIR/performance_summary.stdout"
echo "OUTPUT_DIR=$OUTPUT_DIR"
