#!/usr/bin/env bash
set -uo pipefail

DATA_ROOT=${DATA_ROOT:-/data/cunzhe}
CPU_CORE=${CPU_CORE:-2}
REPO_ROOT=${REPO_ROOT:-$DATA_ROOT/agent-workloads}
ROUNDS=${ROUNDS:-2}
CASE_TIMEOUT_SECONDS=${CASE_TIMEOUT_SECONDS:-1800}
SERIES_TIMESTAMP=${SERIES_TIMESTAMP:-$(date +%Y%m%d_%H%M%S)}
SERIES_DIR=${SERIES_DIR:-$DATA_ROOT/swe_runs/aws36_golden_single_cpu${CPU_CORE}_twice_$(hostname -s)_$SERIES_TIMESTAMP}
STATUS_FILE=$SERIES_DIR/rounds.tsv

mkdir -p "$SERIES_DIR"
printf 'round\tstatus\texit_code\tstarted_at\tfinished_at\trun_dir\n' > "$STATUS_FILE"

overall=0
for round in $(seq 1 "$ROUNDS"); do
  run_dir=$SERIES_DIR/round${round}
  started_at=$(date -Is)
  echo "===== ROUND $round/$ROUNDS START $started_at ====="
  DATA_ROOT="$DATA_ROOT" \
  REPO_ROOT="$REPO_ROOT" \
  CPU_CORE="$CPU_CORE" \
  CASE_TIMEOUT_SECONDS="$CASE_TIMEOUT_SECONDS" \
  RUN_DIR="$run_dir" \
    "$REPO_ROOT/SWE-bench/reproduction/17_run_aws36_golden_single_cpu.sh"
  exit_code=$?
  if [[ $exit_code -eq 0 ]]; then
    status=PASS
  else
    status=FAIL
    overall=1
  fi
  printf '%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$round" "$status" "$exit_code" "$started_at" "$(date -Is)" "$run_dir" \
    >> "$STATUS_FILE"
  echo "===== ROUND $round/$ROUNDS $status ====="
done

echo "SERIES_DIR=$SERIES_DIR"
cat "$STATUS_FILE"
exit "$overall"
