#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
RUNS_ROOT=${SWE_RUNS_ROOT:-/home/higon/cunzhe/swe_runs}
PYTHON=${DGEMM_PYTHON:-/home/higon/cunzhe/agent-workloads/.venv-swe/bin/python}
CPUSET=${PERF_CPUSET:-0-7}
THREADS=${DGEMM_THREADS:-8}
MATRIX_SIZE=${DGEMM_MATRIX_SIZE:-6144}
PASS_SECONDS=${PERF_PASS_SECONDS:-5}
ROUNDS=${PERF_ROUNDS:-1}
WORKLOAD_USER=${SWE_WORKLOAD_USER:-higon}
PASS_FILE=${PERF_SUDO_PASS_FILE:-/home/higon/cunzhe/.secrets/passwd}

STAMP=$(date +%Y%m%d_%H%M%S)
RUN_DIR="$RUNS_ROOT/dgemm_pmu_validation_$STAMP"
UNIT="dgemm-pmu-$STAMP"
CORE_SECONDS=$((9 * PASS_SECONDS * ROUNDS))
DGEMM_SECONDS=$((CORE_SECONDS + 10))
mkdir -p "$RUN_DIR"

if [[ $EUID -eq 0 ]]; then
  SUDO=()
else
  if ! sudo -n true 2>/dev/null; then
    if [[ -r "$PASS_FILE" ]]; then
      sudo -S -p '' -v < "$PASS_FILE"
    else
      sudo -v
    fi
  fi
  SUDO=(sudo -n)
fi

stop_dgemm() {
  "${SUDO[@]}" systemctl stop "$UNIT.service" >/dev/null 2>&1 || true
}
trap stop_dgemm EXIT

"${SUDO[@]}" systemd-run \
  --unit="$UNIT" \
  --slice=swe-sandbox.slice \
  --property="AllowedCPUs=$CPUSET" \
  --property="User=$WORKLOAD_USER" \
  --property="Group=$WORKLOAD_USER" \
  --property="StandardOutput=append:$RUN_DIR/dgemm.log" \
  --property="StandardError=append:$RUN_DIR/dgemm.log" \
  --collect \
  "$PYTHON" "$SCRIPT_DIR/dgemm_8c_demo.py" \
  --cpus "$CPUSET" \
  --threads "$THREADS" \
  --size "$MATRIX_SIZE" \
  --seconds "$DGEMM_SECONDS" \
  > "$RUN_DIR/systemd-run.txt" 2>&1

for _ in {1..20}; do
  if "${SUDO[@]}" systemctl is-active --quiet "$UNIT.service"; then
    break
  fi
  sleep 0.1
done

"${SUDO[@]}" systemctl show "$UNIT.service" \
  --property=Id,MainPID,ControlGroup,AllowedCPUs,ActiveState,SubState \
  > "$RUN_DIR/systemd-unit.txt"

PERF_CPUSET="$CPUSET" \
PERF_OUTPUT_DIR="$RUN_DIR/perf_collect" \
  "$SCRIPT_DIR/collect_emr_pmu_8c.sh" "$RUN_DIR" "$PASS_SECONDS" "$ROUNDS" \
  | tee "$RUN_DIR/collector-result.txt"

while "${SUDO[@]}" systemctl is-active --quiet "$UNIT.service"; do
  sleep 1
done

trap - EXIT
"${SUDO[@]}" chown -R "$WORKLOAD_USER:$WORKLOAD_USER" "$RUN_DIR"
echo "validation_run_dir=$RUN_DIR"
