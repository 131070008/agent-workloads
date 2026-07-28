#!/usr/bin/env bash
set -euo pipefail

RUN_TARGET=${1:-latest}
PASS_SECONDS=${2:-10}
ROUNDS=${3:-3}

RUNS_ROOT=${SWE_RUNS_ROOT:-/home/higon/cunzhe/swe_runs}
CPUSET=${PERF_CPUSET:-0-7}
INTERVAL_MS=${PERF_INTERVAL_MS:-1000}
WORKLOAD_USER=${SWE_WORKLOAD_USER:-higon}
PASS_FILE=${PERF_SUDO_PASS_FILE:-/home/higon/cunzhe/.secrets/passwd}
VALIDATION_SECONDS=${PERF_VALIDATION_SECONDS:-0.1}

if [[ "$RUN_TARGET" == "latest" ]]; then
  RUN_DIR=$(readlink -f "$RUNS_ROOT/fixed_pool_latest")
else
  RUN_DIR=$(readlink -f "$RUN_TARGET")
fi

if [[ ! -d "$RUN_DIR" ]]; then
  echo "Run directory does not exist: $RUN_DIR" >&2
  exit 1
fi

if ! [[ "$PASS_SECONDS" =~ ^[1-9][0-9]*$ ]] || ! [[ "$ROUNDS" =~ ^[1-9][0-9]*$ ]]; then
  echo "PASS_SECONDS and ROUNDS must be positive integers." >&2
  exit 1
fi

WORKLOAD_UID=$(getent passwd "$WORKLOAD_USER" 2>/dev/null | cut -d: -f3 || true)
if [[ -z "$WORKLOAD_UID" ]]; then
  WORKLOAD_UID=$(id -u)
fi

DEFAULT_HOST_CGROUP="user.slice/user-${WORKLOAD_UID}.slice/user@${WORKLOAD_UID}.service/swe.slice/swe-agent.slice"
DEFAULT_SANDBOX_CGROUP="swe.slice/swe-sandbox.slice"
DEFAULT_SYSTEM_CGROUP="system.slice"
CORE_CGROUPS=${PERF_CORE_CGROUPS:-"$DEFAULT_HOST_CGROUP,$DEFAULT_SANDBOX_CGROUP,$DEFAULT_SYSTEM_CGROUP"}

IFS=',' read -r -a CGROUP_PATHS <<< "$CORE_CGROUPS"
for cgroup in "${CGROUP_PATHS[@]}"; do
  if [[ ! -d "/sys/fs/cgroup/$cgroup" ]]; then
    echo "Cgroup is not active: /sys/fs/cgroup/$cgroup" >&2
    echo "Start the grouped SWE pool first, or set PERF_CORE_CGROUPS." >&2
    exit 1
  fi
done

STAMP=$(date +%Y%m%d_%H%M%S)
OUTPUT_DIR=${PERF_OUTPUT_DIR:-"$RUN_DIR/perf_collect/emr_pmu_${STAMP}_$$"}
mkdir -p "$OUTPUT_DIR"

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

PASS_COUNT=9
CORE_SECONDS=$((ROUNDS * PASS_COUNT * PASS_SECONDS))
DDR_SECONDS=$((CORE_SECONDS + 5))
FIRST_CPU=${CPUSET%%[-,]*}
TIMELINE="$OUTPUT_DIR/timeline.tsv"
printf 'timestamp\tround\tpass\tstate\trc\n' > "$TIMELINE"

{
  echo "created_at=$(date --iso-8601=seconds)"
  echo "run_dir=$RUN_DIR"
  echo "output_dir=$OUTPUT_DIR"
  echo "cpuset=$CPUSET"
  echo "interval_ms=$INTERVAL_MS"
  echo "pass_seconds=$PASS_SECONDS"
  echo "rounds=$ROUNDS"
  echo "estimated_core_seconds=$CORE_SECONDS"
  echo "ddr_seconds=$DDR_SECONDS"
  echo "validation_seconds=$VALIDATION_SECONDS"
  echo "core_cgroups=$CORE_CGROUPS"
  echo "pass_order_strategy=rotate_by_3_each_round"
  echo "workload_user=$WORKLOAD_USER"
  echo "workload_uid=$WORKLOAD_UID"
  echo "perf_version=$(perf --version)"
  echo "kernel=$(uname -r)"
  echo "cpu_model=$(lscpu | awk -F: '/Model name/ {sub(/^[[:space:]]+/, "", $2); print $2; exit}')"
} > "$OUTPUT_DIR/config.txt"

for ((round = 1; round <= ROUNDS; round++)); do
  offset=$(( ((round - 1) * 3) % PASS_COUNT ))
  order=()
  for ((index = 0; index < PASS_COUNT; index++)); do
    pass=$(( (index + offset) % PASS_COUNT + 1 ))
    printf -v pass_id '%02d' "$pass"
    order+=("$pass_id")
  done
  printf 'pass_order_round_%s=%s\n' "$round" "$(IFS=,; echo "${order[*]}")" \
    >> "$OUTPUT_DIR/config.txt"
done

run_system_topdown() {
  local round=$1
  local name=01_topdown_l2
  local output="$OUTPUT_DIR/round${round}_${name}.csv"
  local rc

  printf '%s\t%s\t%s\tstart\t-\n' "$(date --iso-8601=seconds)" "$round" "$name" >> "$TIMELINE"
  set +e
  "${SUDO[@]}" perf stat -a -C "$CPUSET" -A \
    -I "$INTERVAL_MS" -x, --topdown --td-level 2 \
    -- sleep "$PASS_SECONDS" > "$output" 2>&1
  rc=$?
  set -e
  printf '%s\t%s\t%s\tend\t%s\n' "$(date --iso-8601=seconds)" "$round" "$name" "$rc" >> "$TIMELINE"
  return "$rc"
}

run_cgroup_pass() {
  local round=$1
  local name=$2
  local events=$3
  local output="$OUTPUT_DIR/round${round}_${name}.csv"
  local rc

  printf '%s\t%s\t%s\tstart\t-\n' "$(date --iso-8601=seconds)" "$round" "$name" >> "$TIMELINE"
  set +e
  "${SUDO[@]}" perf stat -a -C "$CPUSET" -A \
    -I "$INTERVAL_MS" -x, -e "$events" \
    --for-each-cgroup "$CORE_CGROUPS" \
    -- sleep "$PASS_SECONDS" > "$output" 2>&1
  rc=$?
  set -e
  printf '%s\t%s\t%s\tend\t%s\n' "$(date --iso-8601=seconds)" "$round" "$name" "$rc" >> "$TIMELINE"
  return "$rc"
}

BASELINE_EVENTS='task-clock,cycles,instructions,branches,branch-misses,context-switches,cpu-migrations,page-faults,minor-faults,major-faults'
# cycles/instructions use fixed counters and remain in the same scheduling group
# as the four raw events, giving every pass an exact denominator for CPI/MPKI.
LOAD_HITS_EVENTS='{cycles,instructions,cpu/event=0xd1,umask=0x01,name=mem_load_l1_hit/,cpu/event=0xd1,umask=0x02,name=mem_load_l2_hit/,cpu/event=0xd1,umask=0x04,name=mem_load_l3_hit/,cpu/event=0xd1,umask=0x20,name=mem_load_l3_miss/}'
DRAM_LOCALITY_EVENTS='{cycles,instructions,cpu/event=0xd1,umask=0x04,name=retired_l3_hit/,cpu/event=0xd1,umask=0x20,name=retired_l3_miss/,cpu/event=0xd3,umask=0x01,name=l3_miss_local_dram/,cpu/event=0xd3,umask=0x02,name=l3_miss_remote_dram/}'
CACHE_REQUEST_EVENTS='{cycles,instructions,cpu/event=0x24,umask=0xe1,name=l2_demand_data_read/,cpu/event=0x24,umask=0x21,name=l2_demand_data_read_miss/,cpu/event=0x2e,umask=0x4f,name=llc_reference/,cpu/event=0x2e,umask=0x41,name=llc_miss/}'
DTLB_EVENTS='{cycles,instructions,cpu/event=0x12,umask=0x20,name=dtlb_load_stlb_hit/,cpu/event=0x12,umask=0x0e,name=dtlb_load_walk_completed/,cpu/event=0x13,umask=0x20,name=dtlb_store_stlb_hit/,cpu/event=0x13,umask=0x0e,name=dtlb_store_walk_completed/}'
ITLB_EVENTS='{cycles,instructions,cpu/event=0x11,umask=0x20,name=itlb_stlb_hit/,cpu/event=0x11,umask=0x0e,name=itlb_walk_completed/,cpu/event=0x11,umask=0x10,cmask=0x01,name=itlb_walk_active_cycles/,cpu/event=0x80,umask=0x04,name=icache_data_stall_cycles/}'
STALL_EVENTS='{cycles,instructions,cpu/event=0xa3,umask=0x04,cmask=0x04,name=cycle_activity_stalls_total/,cpu/event=0xa3,umask=0x0c,cmask=0x0c,name=cycle_activity_stalls_l1d_miss/,cpu/event=0xa3,umask=0x05,cmask=0x05,name=cycle_activity_stalls_l2_miss/,cpu/event=0xa3,umask=0x06,cmask=0x06,name=cycle_activity_stalls_l3_miss/}'
# Demand-data reads and core L1D/L2 hardware-prefetch reads use one combined
# offcore filter so their traffic share is measured in the same window.
PREFETCH_EVENTS='{cycles,instructions,cpu/event=0x2a,umask=0x01,offcore_rsp=0x10001,name=ocr_demand_data_any/,cpu/event=0x2b,umask=0x01,offcore_rsp=0x10470,name=ocr_hwpf_l1d_l2_any/,cpu/event=0x24,umask=0x30,name=l2_hwpf_miss/,cpu/event=0x26,umask=0x04,name=l2_useless_hwpf/}'

run_pass() {
  local round=$1
  local pass_id=$2

  case "$pass_id" in
    01) run_system_topdown "$round" ;;
    02) run_cgroup_pass "$round" 02_core_and_scheduler "$BASELINE_EVENTS" ;;
    03) run_cgroup_pass "$round" 03_retired_load_levels "$LOAD_HITS_EVENTS" ;;
    04) run_cgroup_pass "$round" 04_dram_locality "$DRAM_LOCALITY_EVENTS" ;;
    05) run_cgroup_pass "$round" 05_cache_requests "$CACHE_REQUEST_EVENTS" ;;
    06) run_cgroup_pass "$round" 06_dtlb "$DTLB_EVENTS" ;;
    07) run_cgroup_pass "$round" 07_itlb_and_icache "$ITLB_EVENTS" ;;
    08) run_cgroup_pass "$round" 08_memory_stalls "$STALL_EVENTS" ;;
    09) run_cgroup_pass "$round" 09_demand_prefetch "$PREFETCH_EVENTS" ;;
    *)
      echo "Unknown PMU pass: $pass_id" >&2
      return 1
      ;;
  esac
}

validate_event_group() {
  local name=$1
  local events=$2
  local output="$OUTPUT_DIR/validate_${name}.txt"
  local rc

  set +e
  "${SUDO[@]}" perf stat -a -C "$FIRST_CPU" -e "$events" \
    -- sleep "$VALIDATION_SECONDS" > "$output" 2>&1
  rc=$?
  set -e
  if grep -q -E '<not counted>|<not supported>' "$output"; then
    rc=1
  fi
  return "$rc"
}

DDR_EVENTS='uncore_imc_0/event=0x05,umask=0xcf,name=imc0_read_cas/,uncore_imc_0/event=0x05,umask=0xf0,name=imc0_write_cas/'
for imc in 1 2 3 4 5 6 7; do
  DDR_EVENTS+=",uncore_imc_${imc}/event=0x05,umask=0xcf,name=imc${imc}_read_cas/"
  DDR_EVENTS+=",uncore_imc_${imc}/event=0x05,umask=0xf0,name=imc${imc}_write_cas/"
done

FAILURES=0
validate_event_group 02_core_and_scheduler "$BASELINE_EVENTS" || FAILURES=$((FAILURES + 1))
validate_event_group 03_retired_load_levels "$LOAD_HITS_EVENTS" || FAILURES=$((FAILURES + 1))
validate_event_group 04_dram_locality "$DRAM_LOCALITY_EVENTS" || FAILURES=$((FAILURES + 1))
validate_event_group 05_cache_requests "$CACHE_REQUEST_EVENTS" || FAILURES=$((FAILURES + 1))
validate_event_group 06_dtlb "$DTLB_EVENTS" || FAILURES=$((FAILURES + 1))
validate_event_group 07_itlb_and_icache "$ITLB_EVENTS" || FAILURES=$((FAILURES + 1))
validate_event_group 08_memory_stalls "$STALL_EVENTS" || FAILURES=$((FAILURES + 1))
validate_event_group 09_demand_prefetch "$PREFETCH_EVENTS" || FAILURES=$((FAILURES + 1))

if ((FAILURES != 0)); then
  echo "One or more PMU event groups failed the system-wide scheduling check." >&2
  echo "See $OUTPUT_DIR/validate_*.txt" >&2
  exit 1
fi

"${SUDO[@]}" perf stat -a --per-socket -I "$INTERVAL_MS" -x, \
  -e "$DDR_EVENTS" -- sleep "$DDR_SECONDS" \
  > "$OUTPUT_DIR/ddr_imc.csv" 2>&1 &
DDR_PID=$!

for ((round = 1; round <= ROUNDS; round++)); do
  offset=$(( ((round - 1) * 3) % PASS_COUNT ))
  for ((index = 0; index < PASS_COUNT; index++)); do
    pass=$(( (index + offset) % PASS_COUNT + 1 ))
    printf -v pass_id '%02d' "$pass"
    run_pass "$round" "$pass_id" || FAILURES=$((FAILURES + 1))
  done
done

set +e
wait "$DDR_PID"
DDR_RC=$?
set -e
if ((DDR_RC != 0)); then
  FAILURES=$((FAILURES + 1))
fi

grep -R '<not supported>' "$OUTPUT_DIR" \
  > "$OUTPUT_DIR/event_unsupported.txt" 2>/dev/null || true
grep -R '<not counted>' "$OUTPUT_DIR" \
  > "$OUTPUT_DIR/cgroup_idle_samples.txt" 2>/dev/null || true

{
  echo "completed_at=$(date --iso-8601=seconds)"
  echo "failed_passes=$FAILURES"
  echo "ddr_rc=$DDR_RC"
  echo "unsupported_lines=$(wc -l < "$OUTPUT_DIR/event_unsupported.txt")"
  echo "cgroup_idle_lines=$(wc -l < "$OUTPUT_DIR/cgroup_idle_samples.txt")"
  echo "output_dir=$OUTPUT_DIR"
} > "$OUTPUT_DIR/result.txt"

cat "$OUTPUT_DIR/result.txt"
if ((FAILURES != 0)); then
  exit 1
fi
