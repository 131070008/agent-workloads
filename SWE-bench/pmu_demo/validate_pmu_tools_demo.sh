#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PMU_TOOLS=${PMU_TOOLS:-/home/higon/cunzhe/tools/pmu-tools}
RUNS_ROOT=${SWE_RUNS_ROOT:-/home/higon/cunzhe/swe_runs}
PASS_FILE=${PERF_SUDO_PASS_FILE:-/home/higon/cunzhe/.secrets/passwd}
CPU=${PERF_DEMO_CPU:-0}
SECONDS_PER_MODE=${PERF_DEMO_SECONDS:-1}
STAMP=$(date +%Y%m%d_%H%M%S)
OUTPUT_DIR=${PERF_OUTPUT_DIR:-"$RUNS_ROOT/pmu_tools_demo_$STAMP"}
DEMO="$OUTPUT_DIR/pmu_mix_demo"

mkdir -p "$OUTPUT_DIR"
test -x "$PMU_TOOLS/toplev.py"
test -x "$PMU_TOOLS/ocperf.py"

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

ORIGINAL_PARANOID=$(cat /proc/sys/kernel/perf_event_paranoid)
ORIGINAL_WATCHDOG=$(cat /proc/sys/kernel/nmi_watchdog)

restore_system_settings() {
  "${SUDO[@]}" sysctl -q -w "kernel.perf_event_paranoid=$ORIGINAL_PARANOID" || true
  "${SUDO[@]}" sysctl -q -w "kernel.nmi_watchdog=$ORIGINAL_WATCHDOG" || true
  "${SUDO[@]}" chown -R "$(id -u):$(id -g)" "$OUTPUT_DIR" || true
}
trap restore_system_settings EXIT

"${SUDO[@]}" sysctl -q -w kernel.perf_event_paranoid=-1
"${SUDO[@]}" sysctl -q -w kernel.nmi_watchdog=0

gcc -O3 -march=native -fno-omit-frame-pointer \
  -fno-if-conversion -fno-if-conversion2 \
  "$SCRIPT_DIR/pmu_mix_demo.c" -o "$DEMO"

{
  echo "created_at=$(date --iso-8601=seconds)"
  echo "cpu=$CPU"
  echo "seconds_per_mode=$SECONDS_PER_MODE"
  echo "cpu_model=$(lscpu | awk -F: '/Model name/ {sub(/^[[:space:]]+/, "", $2); print $2; exit}')"
  echo "kernel=$(uname -r)"
  echo "perf_version=$(perf --version)"
  echo "pmu_tools_commit=$(git -C "$PMU_TOOLS" rev-parse HEAD)"
  echo "pmu_name=$(cat /sys/bus/event_source/devices/cpu/caps/pmu_name)"
  echo "original_perf_event_paranoid=$ORIGINAL_PARANOID"
  echo "original_nmi_watchdog=$ORIGINAL_WATCHDOG"
  "$PMU_TOOLS/toplev.py" --version 2>&1 | tail -1
} > "$OUTPUT_DIR/config.txt"

for mode in int fp branch mixed; do
  taskset -c "$CPU" "$DEMO" "$mode" "$SECONDS_PER_MODE" \
    > "$OUTPUT_DIR/${mode}_baseline.txt"
done

BASE_EVENTS='cycles,instructions,branches,branch-misses,mem_inst_retired.all_loads,mem_inst_retired.all_stores'
for mode in int fp branch mixed; do
  "$PMU_TOOLS/ocperf.py" stat -x, -e "$BASE_EVENTS" \
    -- taskset -c "$CPU" "$DEMO" "$mode" "$SECONDS_PER_MODE" \
    > "$OUTPUT_DIR/${mode}_base_events.csv" 2>&1
done

FP_EVENTS='cycles,instructions,fp_arith_inst_retired.scalar_double,fp_arith_inst_retired.128b_packed_double,fp_arith_inst_retired.256b_packed_double,fp_arith_inst_retired.512b_packed_double'
"$PMU_TOOLS/ocperf.py" stat -x, -e "$FP_EVENTS" \
  -- taskset -c "$CPU" "$DEMO" fp "$SECONDS_PER_MODE" \
  > "$OUTPUT_DIR/fp_width_events.csv" 2>&1

BRANCH_EVENTS='cycles,instructions,br_inst_retired.all_branches,br_inst_retired.cond,br_inst_retired.indirect,br_inst_retired.near_call,br_inst_retired.near_return'
"$PMU_TOOLS/ocperf.py" stat -x, -e "$BRANCH_EVENTS" \
  -- taskset -c "$CPU" "$DEMO" branch "$SECONDS_PER_MODE" \
  > "$OUTPUT_DIR/branch_type_events.csv" 2>&1

set +e
"$PMU_TOOLS/toplev.py" -l3 --single-thread --no-uncore --no-multiplex \
  --verbose --no-desc -x, \
  taskset -c "$CPU" "$DEMO" mixed "$SECONDS_PER_MODE" \
  > "$OUTPUT_DIR/toplev_l3_tree.csv" 2>&1
TOPLEV_TREE_RC=$?

"$PMU_TOOLS/toplev.py" --single-thread --no-uncore --no-multiplex \
  --nodes '!+Retiring*/5,+MUX' --verbose --no-desc -x, \
  taskset -c "$CPU" "$DEMO" mixed "$SECONDS_PER_MODE" \
  > "$OUTPUT_DIR/toplev_retiring_l5.csv" 2>&1
TOPLEV_RETIRING_RC=$?
set -e

grep -R -E '<not supported>|<not counted>|Traceback|No permission' "$OUTPUT_DIR" \
  > "$OUTPUT_DIR/event_errors.txt" 2>/dev/null || true
grep -R -E 'event not found' "$OUTPUT_DIR" \
  > "$OUTPUT_DIR/model_event_warnings.txt" 2>/dev/null || true

{
  echo "completed_at=$(date --iso-8601=seconds)"
  echo "toplev_tree_rc=$TOPLEV_TREE_RC"
  echo "toplev_retiring_rc=$TOPLEV_RETIRING_RC"
  echo "event_error_lines=$(wc -l < "$OUTPUT_DIR/event_errors.txt")"
  echo "model_event_warning_lines=$(wc -l < "$OUTPUT_DIR/model_event_warnings.txt")"
  echo "output_dir=$OUTPUT_DIR"
} > "$OUTPUT_DIR/result.txt"

cat "$OUTPUT_DIR/result.txt"
if ((TOPLEV_TREE_RC != 0)) || ((TOPLEV_RETIRING_RC != 0)) || [[ -s "$OUTPUT_DIR/event_errors.txt" ]]; then
  exit 1
fi
