#!/usr/bin/env bash
set -euo pipefail

ROOT=/home/higon/cunzhe/agent-workloads
PYTHON=$ROOT/.venv-swe/bin/python
WORKERS=${SWE_WORKER_SWEEP:-"1 2 4 8 16 30"}
REPEATS=${SWE_REPEATS:-1}
PRIMARY=${SWE_PRIMARY_CONCURRENCY:-k16}
STAMP=$(date +%Y%m%d_%H%M%S)
OUTPUT_ROOT=${SWE_OUTPUT_ROOT:-/home/higon/cunzhe/swe_runs/golden_perf/fixed_sweep_$STAMP}

mkdir -p "$OUTPUT_ROOT"
RUN_ARGS=()
for workers in $WORKERS; do
  run_dir="$OUTPUT_ROOT/k$workers"
  SWE_OUTPUT_DIR="$run_dir" \
    "$ROOT/SWE-bench/run_swe_golden_multi_perf.sh" "$workers" "$REPEATS"
  RUN_ARGS+=(--run "k$workers=$run_dir")
done

"$PYTHON" "$ROOT/SWE-bench/compare_swe_golden_concurrency.py" \
  "${RUN_ARGS[@]}" \
  --baseline k1 \
  --primary "$PRIMARY" \
  --output-dir "$OUTPUT_ROOT/comparison"

echo "OUTPUT_ROOT=$OUTPUT_ROOT"
