#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
RUN_TARGET=${1:-latest}
RAW_PASS_SECONDS=${2:-5}
TOPLEV_PASS_SECONDS=${3:-3}

RUNS_ROOT=${SWE_RUNS_ROOT:-/home/higon/cunzhe/swe_runs}
PMU_TOOLS=${PMU_TOOLS:-/home/higon/cunzhe/tools/pmu-tools}
EMR_TMA_COLLECTOR=${SWE_EMR_TMA_COLLECTOR:-"$SCRIPT_DIR/collect_emr_tma52_l1_l4.py"}
EMR_TMA_MANIFEST=${SWE_EMR_TMA_MANIFEST:-"$SCRIPT_DIR/pmu_emr/emr_topdown_l1_l4.json"}
EMR_L1_L2_SUMMARIZER=${SWE_EMR_L1_L2_SUMMARIZER:-"$SCRIPT_DIR/summarize_emr_topdown_l1_l2.py"}
CPUSET=${PERF_CPUSET:-0-7}
INTERVAL_MS=${PERF_INTERVAL_MS:-1000}
WORKLOAD_USER=${SWE_WORKLOAD_USER:-higon}
PASS_FILE=${PERF_SUDO_PASS_FILE:-/home/higon/cunzhe/.secrets/passwd}
VALIDATION_SECONDS=${PERF_VALIDATION_SECONDS:-0.2}

if [[ "$RUN_TARGET" == "latest" ]]; then
  RUN_DIR=$(readlink -f "$RUNS_ROOT/fixed_pool_latest")
else
  RUN_DIR=$(readlink -f "$RUN_TARGET")
fi

if [[ ! -d "$RUN_DIR" ]]; then
  echo "Run directory does not exist: $RUN_DIR" >&2
  exit 1
fi
if ! [[ "$RAW_PASS_SECONDS" =~ ^[1-9][0-9]*$ ]]; then
  echo "RAW_PASS_SECONDS must be a positive integer." >&2
  exit 1
fi
if ! [[ "$TOPLEV_PASS_SECONDS" =~ ^[1-9][0-9]*$ ]]; then
  echo "TOPLEV_PASS_SECONDS must be a positive integer." >&2
  exit 1
fi
test -x "$PMU_TOOLS/ocperf.py"
test -f "$EMR_TMA_COLLECTOR"
test -f "$EMR_TMA_MANIFEST"
test -f "$EMR_L1_L2_SUMMARIZER"

WORKLOAD_UID=$(getent passwd "$WORKLOAD_USER" | cut -d: -f3)
HOST_CGROUP=${PERF_HOST_CGROUP:-"user.slice/user-${WORKLOAD_UID}.slice/user@${WORKLOAD_UID}.service/swe.slice/swe-agent.slice"}
SANDBOX_CGROUP=${PERF_SANDBOX_CGROUP:-"swe.slice/swe-sandbox.slice"}
SYSTEM_CGROUP=${PERF_SYSTEM_CGROUP:-"system.slice"}
CORE_CGROUPS=${PERF_CORE_CGROUPS:-"$HOST_CGROUP,$SANDBOX_CGROUP,$SYSTEM_CGROUP"}

for cgroup in "$HOST_CGROUP" "$SANDBOX_CGROUP" "$SYSTEM_CGROUP"; do
  if [[ ! -d "/sys/fs/cgroup/$cgroup" ]]; then
    echo "Cgroup is not active: /sys/fs/cgroup/$cgroup" >&2
    exit 1
  fi
done

STAMP=$(date +%Y%m%d_%H%M%S)
OUTPUT_DIR=${PERF_OUTPUT_DIR:-"$RUN_DIR/perf_collect/emr_pmu_detailed_${STAMP}_$$"}
mkdir -p "$OUTPUT_DIR/raw_cgroup" "$OUTPUT_DIR/raw_global" \
  "$OUTPUT_DIR/official_emr_tma52"

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
  "${SUDO[@]}" chown -R "$WORKLOAD_USER:$WORKLOAD_USER" "$OUTPUT_DIR" || true
}
trap restore_system_settings EXIT

"${SUDO[@]}" sysctl -q -w kernel.perf_event_paranoid=-1
"${SUDO[@]}" sysctl -q -w kernel.nmi_watchdog=0

FIRST_CPU=${CPUSET%%[-,]*}
TIMELINE="$OUTPUT_DIR/timeline.tsv"
printf 'timestamp\tcollector\tname\tstate\trc\n' > "$TIMELINE"

{
  echo "created_at=$(date --iso-8601=seconds)"
  echo "run_dir=$RUN_DIR"
  echo "output_dir=$OUTPUT_DIR"
  echo "cpuset=$CPUSET"
  echo "raw_pass_seconds=$RAW_PASS_SECONDS"
  echo "global_pass_seconds=$TOPLEV_PASS_SECONDS"
  echo "interval_ms=$INTERVAL_MS"
  echo "official_tma=Intel EMR metrics v1.4 / TMA 5.2 Full"
  echo "official_tma_scope=Host/Sandbox/System cgroups plus all tasks on CPUs 0-7"
  echo "official_tma_levels=L1-L4"
  echo "official_tma_manifest=$EMR_TMA_MANIFEST"
  echo "host_cgroup=$HOST_CGROUP"
  echo "sandbox_cgroup=$SANDBOX_CGROUP"
  echo "system_cgroup=$SYSTEM_CGROUP"
  echo "core_cgroups=$CORE_CGROUPS"
  echo "perf_version=$(perf --version)"
  echo "kernel=$(uname -r)"
  echo "cpu_model=$(lscpu | awk -F: '/Model name/ {sub(/^[[:space:]]+/, "", $2); print $2; exit}')"
  echo "pmu_name=$(cat /sys/bus/event_source/devices/cpu/caps/pmu_name)"
  echo "pmu_tools_commit=$(git -C "$PMU_TOOLS" rev-parse HEAD)"
  echo "original_perf_event_paranoid=$ORIGINAL_PARANOID"
  echo "original_nmi_watchdog=$ORIGINAL_WATCHDOG"
} > "$OUTPUT_DIR/config.txt"

BASELINE_EVENTS='task-clock,cycles,instructions,branches,branch-misses,context-switches,cpu-migrations,page-faults,minor-faults,major-faults'
BRANCH_BASIC_EVENTS='cycles,instructions,br_inst_retired.all_branches,br_inst_retired.cond,br_inst_retired.indirect,br_inst_retired.near_call'
BRANCH_DIRECTION_EVENTS='cycles,instructions,br_inst_retired.near_return,br_inst_retired.cond_taken,br_inst_retired.cond_ntaken,br_inst_retired.near_taken'
RETIRED_MIX_EVENTS='cycles,instructions,mem_inst_retired.all_loads,mem_inst_retired.all_stores,inst_retired.macro_fused,uops_retired.heavy'
FP_SCALAR_128_EVENTS='cycles,instructions,fp_arith_inst_retired.scalar_single,fp_arith_inst_retired.scalar_double,fp_arith_inst_retired.128b_packed_single,fp_arith_inst_retired.128b_packed_double'
FP_256_512_EVENTS='cycles,instructions,fp_arith_inst_retired.256b_packed_single,fp_arith_inst_retired.256b_packed_double,fp_arith_inst_retired.512b_packed_single,fp_arith_inst_retired.512b_packed_double'

LOAD_HITS_EVENTS='{cycles,instructions,cpu/event=0xd1,umask=0x01,name=mem_load_l1_hit/,cpu/event=0xd1,umask=0x02,name=mem_load_l2_hit/,cpu/event=0xd1,umask=0x04,name=mem_load_l3_hit/,cpu/event=0xd1,umask=0x20,name=mem_load_l3_miss/}'
DRAM_LOCALITY_EVENTS='{cycles,instructions,cpu/event=0xd1,umask=0x04,name=retired_l3_hit/,cpu/event=0xd1,umask=0x20,name=retired_l3_miss/,cpu/event=0xd3,umask=0x01,name=l3_miss_local_dram/,cpu/event=0xd3,umask=0x02,name=l3_miss_remote_dram/}'
CACHE_REQUEST_EVENTS='{cycles,instructions,cpu/event=0x24,umask=0xe1,name=l2_demand_data_read/,cpu/event=0x24,umask=0x21,name=l2_demand_data_read_miss/,cpu/event=0x2e,umask=0x4f,name=llc_reference/,cpu/event=0x2e,umask=0x41,name=llc_miss/}'
DTLB_EVENTS='{cycles,instructions,cpu/event=0x12,umask=0x20,name=dtlb_load_stlb_hit/,cpu/event=0x12,umask=0x0e,name=dtlb_load_walk_completed/,cpu/event=0x13,umask=0x20,name=dtlb_store_stlb_hit/,cpu/event=0x13,umask=0x0e,name=dtlb_store_walk_completed/}'
ITLB_EVENTS='{cycles,instructions,cpu/event=0x11,umask=0x20,name=itlb_stlb_hit/,cpu/event=0x11,umask=0x0e,name=itlb_walk_completed/,cpu/event=0x11,umask=0x10,cmask=0x01,name=itlb_walk_active_cycles/,cpu/event=0x80,umask=0x04,name=icache_data_stall_cycles/}'
STALL_EVENTS='{cycles,instructions,cpu/event=0xa3,umask=0x04,cmask=0x04,name=cycle_activity_stalls_total/,cpu/event=0xa3,umask=0x0c,cmask=0x0c,name=cycle_activity_stalls_l1d_miss/,cpu/event=0xa3,umask=0x05,cmask=0x05,name=cycle_activity_stalls_l2_miss/,cpu/event=0xa3,umask=0x06,cmask=0x06,name=cycle_activity_stalls_l3_miss/}'
PREFETCH_EVENTS='{cycles,instructions,cpu/event=0x2a,umask=0x01,offcore_rsp=0x10001,name=ocr_demand_data_any/,cpu/event=0x2b,umask=0x01,offcore_rsp=0x10470,name=ocr_hwpf_l1d_l2_any/,cpu/event=0x24,umask=0x30,name=l2_hwpf_miss/,cpu/event=0x26,umask=0x04,name=l2_useless_hwpf/}'

FAILURES=0

validate_native_group() {
  local name=$1
  local events=$2
  local output="$OUTPUT_DIR/validate_native_${name}.txt"
  local rc

  set +e
  "${SUDO[@]}" perf stat -a -C "$FIRST_CPU" -e "$events" \
    -- sleep "$VALIDATION_SECONDS" > "$output" 2>&1
  rc=$?
  set -e
  if grep -q -E '<not supported>|No permission|Access to performance' "$output"; then
    rc=1
  fi
  return "$rc"
}

validate_symbolic_group() {
  local name=$1
  local events=$2
  local output="$OUTPUT_DIR/validate_symbolic_${name}.txt"
  local rc

  set +e
  "$PMU_TOOLS/ocperf.py" stat -a -C "$FIRST_CPU" -x, -e "$events" \
    -- sleep "$VALIDATION_SECONDS" > "$output" 2>&1
  rc=$?
  set -e
  if grep -q -E '<not supported>|No permission|Access to performance|event not found' "$output"; then
    rc=1
  fi
  return "$rc"
}

run_native_cgroup_pass() {
  local name=$1
  local events=$2
  local output="$OUTPUT_DIR/raw_cgroup/${name}.csv"
  local rc

  printf '%s\traw\t%s\tstart\t-\n' "$(date --iso-8601=seconds)" "$name" >> "$TIMELINE"
  set +e
  "${SUDO[@]}" perf stat -a -C "$CPUSET" -A -I "$INTERVAL_MS" -x, \
    -e "$events" --for-each-cgroup "$CORE_CGROUPS" \
    -- sleep "$RAW_PASS_SECONDS" > "$output" 2>&1
  rc=$?
  set -e
  printf '%s\traw\t%s\tend\t%s\n' "$(date --iso-8601=seconds)" "$name" "$rc" >> "$TIMELINE"
  return "$rc"
}

run_symbolic_cgroup_pass() {
  local name=$1
  local events=$2
  local output="$OUTPUT_DIR/raw_cgroup/${name}.csv"
  local rc

  printf '%s\traw\t%s\tstart\t-\n' "$(date --iso-8601=seconds)" "$name" >> "$TIMELINE"
  set +e
  "$PMU_TOOLS/ocperf.py" stat -a -C "$CPUSET" -A -I "$INTERVAL_MS" -x, \
    -e "$events" --for-each-cgroup "$CORE_CGROUPS" \
    -- sleep "$RAW_PASS_SECONDS" > "$output" 2>&1
  rc=$?
  set -e
  printf '%s\traw\t%s\tend\t%s\n' "$(date --iso-8601=seconds)" "$name" "$rc" >> "$TIMELINE"
  return "$rc"
}

run_native_global_pass() {
  local name=$1
  local events=$2
  local output="$OUTPUT_DIR/raw_global/${name}.csv"
  local rc

  printf '%s\traw_global\t%s\tstart\t-\n' "$(date --iso-8601=seconds)" "$name" >> "$TIMELINE"
  set +e
  "${SUDO[@]}" perf stat -a -C "$CPUSET" -A -I "$INTERVAL_MS" -x, \
    -e "$events" -- sleep "$TOPLEV_PASS_SECONDS" > "$output" 2>&1
  rc=$?
  set -e
  printf '%s\traw_global\t%s\tend\t%s\n' "$(date --iso-8601=seconds)" "$name" "$rc" >> "$TIMELINE"
  return "$rc"
}

run_symbolic_global_pass() {
  local name=$1
  local events=$2
  local output="$OUTPUT_DIR/raw_global/${name}.csv"
  local rc

  printf '%s\traw_global\t%s\tstart\t-\n' "$(date --iso-8601=seconds)" "$name" >> "$TIMELINE"
  set +e
  "$PMU_TOOLS/ocperf.py" stat -a -C "$CPUSET" -A -I "$INTERVAL_MS" -x, \
    -e "$events" -- sleep "$TOPLEV_PASS_SECONDS" > "$output" 2>&1
  rc=$?
  set -e
  printf '%s\traw_global\t%s\tend\t%s\n' "$(date --iso-8601=seconds)" "$name" "$rc" >> "$TIMELINE"
  return "$rc"
}

run_native_pair() {
  run_native_cgroup_pass "$1" "$2" || FAILURES=$((FAILURES + 1))
  run_native_global_pass "$1" "$2" || FAILURES=$((FAILURES + 1))
}

run_symbolic_pair() {
  run_symbolic_cgroup_pass "$1" "$2" || FAILURES=$((FAILURES + 1))
  run_symbolic_global_pass "$1" "$2" || FAILURES=$((FAILURES + 1))
}

validate_native_group baseline "$BASELINE_EVENTS" || FAILURES=$((FAILURES + 1))
validate_symbolic_group branch_basic "$BRANCH_BASIC_EVENTS" || FAILURES=$((FAILURES + 1))
validate_symbolic_group branch_direction "$BRANCH_DIRECTION_EVENTS" || FAILURES=$((FAILURES + 1))
validate_symbolic_group retired_mix "$RETIRED_MIX_EVENTS" || FAILURES=$((FAILURES + 1))
validate_symbolic_group fp_scalar_128 "$FP_SCALAR_128_EVENTS" || FAILURES=$((FAILURES + 1))
validate_symbolic_group fp_256_512 "$FP_256_512_EVENTS" || FAILURES=$((FAILURES + 1))
validate_native_group load_hits "$LOAD_HITS_EVENTS" || FAILURES=$((FAILURES + 1))
validate_native_group dram_locality "$DRAM_LOCALITY_EVENTS" || FAILURES=$((FAILURES + 1))
validate_native_group cache_requests "$CACHE_REQUEST_EVENTS" || FAILURES=$((FAILURES + 1))
validate_native_group dtlb "$DTLB_EVENTS" || FAILURES=$((FAILURES + 1))
validate_native_group itlb "$ITLB_EVENTS" || FAILURES=$((FAILURES + 1))
validate_native_group stalls "$STALL_EVENTS" || FAILURES=$((FAILURES + 1))
validate_native_group prefetch "$PREFETCH_EVENTS" || FAILURES=$((FAILURES + 1))

if ((FAILURES != 0)); then
  echo "One or more PMU event groups failed validation." >&2
  exit 1
fi

run_native_pair 01_core_scheduler_faults "$BASELINE_EVENTS"
run_symbolic_pair 02_branch_basic "$BRANCH_BASIC_EVENTS"
run_symbolic_pair 03_branch_direction "$BRANCH_DIRECTION_EVENTS"
run_symbolic_pair 04_retired_mix "$RETIRED_MIX_EVENTS"
run_symbolic_pair 05_fp_scalar_128 "$FP_SCALAR_128_EVENTS"
run_symbolic_pair 06_fp_256_512 "$FP_256_512_EVENTS"
run_native_pair 07_retired_load_levels "$LOAD_HITS_EVENTS"
run_native_pair 08_dram_locality "$DRAM_LOCALITY_EVENTS"
run_native_pair 09_cache_requests "$CACHE_REQUEST_EVENTS"
run_native_pair 10_dtlb "$DTLB_EVENTS"
run_native_pair 11_itlb_icache "$ITLB_EVENTS"
run_native_pair 12_memory_stalls "$STALL_EVENTS"
run_native_pair 13_demand_prefetch "$PREFETCH_EVENTS"

printf '%s\tofficial_emr_tma52\tl1_l4_cgroup_and_global\tstart\t-\n' \
  "$(date --iso-8601=seconds)" >> "$TIMELINE"
set +e
"${SUDO[@]}" python3 "$EMR_TMA_COLLECTOR" \
  --manifest "$EMR_TMA_MANIFEST" \
  --output-dir "$OUTPUT_DIR/official_emr_tma52" \
  --cpuset "$CPUSET" \
  --cgroups "$CORE_CGROUPS" \
  --cgroup-seconds "$RAW_PASS_SECONDS" \
  --global-seconds "$TOPLEV_PASS_SECONDS" \
  --validation-seconds "$VALIDATION_SECONDS" \
  > "$OUTPUT_DIR/official_emr_tma52_collector.log" 2>&1
OFFICIAL_TMA_RC=$?
CGROUP_SUMMARY_RC=0
GLOBAL_SUMMARY_RC=0
if ((OFFICIAL_TMA_RC == 0)); then
  python3 "$EMR_L1_L2_SUMMARIZER" \
    --input "$OUTPUT_DIR/official_emr_tma52/raw_cgroup/00_fixed_perf_metrics.csv" \
    --output-csv "$OUTPUT_DIR/official_emr_tma52/cgroup_l1_l2_metrics.csv" \
    --output-text "$OUTPUT_DIR/official_emr_tma52/cgroup_l1_l2_readable.txt"
  CGROUP_SUMMARY_RC=$?
  python3 "$EMR_L1_L2_SUMMARIZER" \
    --input "$OUTPUT_DIR/official_emr_tma52/raw_global/00_fixed_perf_metrics.csv" \
    --output-csv "$OUTPUT_DIR/official_emr_tma52/global_l1_l2_metrics.csv" \
    --output-text "$OUTPUT_DIR/official_emr_tma52/global_l1_l2_readable.txt"
  GLOBAL_SUMMARY_RC=$?
fi
set -e
printf '%s\tofficial_emr_tma52\tl1_l4_cgroup_and_global\tend\t%s\n' \
  "$(date --iso-8601=seconds)" "$OFFICIAL_TMA_RC" >> "$TIMELINE"
if ((OFFICIAL_TMA_RC != 0 || CGROUP_SUMMARY_RC != 0 || GLOBAL_SUMMARY_RC != 0)); then
  FAILURES=$((FAILURES + 1))
fi

grep -R -E '<not supported>|Traceback|No permission|Access to performance' \
  "$OUTPUT_DIR" > "$OUTPUT_DIR/event_errors.txt" 2>/dev/null || true
awk -F, '$8 ~ /^[0-9]+([.][0-9]+)?$/ {print $8}' \
  "$OUTPUT_DIR"/raw_cgroup/*.csv | sort -nu \
  > "$OUTPUT_DIR/raw_running_percentages.txt"
awk -F, '$5 ~ /^(task-clock|context-switches|cpu-migrations|page-faults|minor-faults|major-faults)$/ && $8 ~ /^[0-9]+([.][0-9]+)?$/ {print $8}' \
  "$OUTPUT_DIR"/raw_cgroup/*.csv | sort -nu \
  > "$OUTPUT_DIR/raw_software_running_percentages.txt"
awk -F, '$5 !~ /^(task-clock|context-switches|cpu-migrations|page-faults|minor-faults|major-faults)$/ && $8 ~ /^[0-9]+([.][0-9]+)?$/ && ($8 + 0) < 99.0 {print}' \
  "$OUTPUT_DIR"/raw_cgroup/*.csv \
  > "$OUTPUT_DIR/raw_hardware_below_99_percent.txt"
awk -F, '$7 ~ /^[0-9]+([.][0-9]+)?$/ {print $7}' \
  "$OUTPUT_DIR"/raw_global/*.csv | sort -nu \
  > "$OUTPUT_DIR/raw_global_running_percentages.txt"
awk -F, '$7 ~ /^[0-9]+([.][0-9]+)?$/ && ($7 + 0) < 99.0 {print}' \
  "$OUTPUT_DIR"/raw_global/*.csv \
  > "$OUTPUT_DIR/raw_global_below_99_percent.txt"

if [[ -s "$OUTPUT_DIR/event_errors.txt" ]]; then
  FAILURES=$((FAILURES + 1))
fi
if [[ -s "$OUTPUT_DIR/raw_hardware_below_99_percent.txt" ]]; then
  FAILURES=$((FAILURES + 1))
fi
if [[ -s "$OUTPUT_DIR/raw_global_below_99_percent.txt" ]]; then
  FAILURES=$((FAILURES + 1))
fi

{
  echo "completed_at=$(date --iso-8601=seconds)"
  echo "failed_steps=$FAILURES"
  echo "event_error_lines=$(wc -l < "$OUTPUT_DIR/event_errors.txt")"
  echo "official_tma_rc=$OFFICIAL_TMA_RC"
  echo "official_tma_cgroup_l1_l2_summary_rc=$CGROUP_SUMMARY_RC"
  echo "official_tma_global_l1_l2_summary_rc=$GLOBAL_SUMMARY_RC"
  echo "raw_running_percentages=$(paste -sd, "$OUTPUT_DIR/raw_running_percentages.txt")"
  echo "raw_software_running_percentages=$(paste -sd, "$OUTPUT_DIR/raw_software_running_percentages.txt")"
  echo "raw_hardware_below_99_percent_lines=$(wc -l < "$OUTPUT_DIR/raw_hardware_below_99_percent.txt")"
  echo "raw_global_running_percentages=$(paste -sd, "$OUTPUT_DIR/raw_global_running_percentages.txt")"
  echo "raw_global_below_99_percent_lines=$(wc -l < "$OUTPUT_DIR/raw_global_below_99_percent.txt")"
  echo "output_dir=$OUTPUT_DIR"
} > "$OUTPUT_DIR/result.txt"

cat "$OUTPUT_DIR/result.txt"
if ((FAILURES != 0)); then
  exit 1
fi
