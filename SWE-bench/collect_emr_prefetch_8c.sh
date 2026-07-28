#!/usr/bin/env bash
set -euo pipefail

RUN_TARGET=${1:-latest}
PASS_SECONDS=${2:-10}
ROUNDS=${3:-2}

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
CORE_CGROUPS=${PERF_CORE_CGROUPS:-"$DEFAULT_HOST_CGROUP,$DEFAULT_SANDBOX_CGROUP"}

IFS=',' read -r -a CGROUP_PATHS <<< "$CORE_CGROUPS"
for cgroup in "${CGROUP_PATHS[@]}"; do
  if [[ ! -d "/sys/fs/cgroup/$cgroup" ]]; then
    echo "Cgroup is not active: /sys/fs/cgroup/$cgroup" >&2
    echo "Start the grouped SWE pool first, or set PERF_CORE_CGROUPS." >&2
    exit 1
  fi
done

STAMP=$(date +%Y%m%d_%H%M%S)
OUTPUT_DIR=${PERF_OUTPUT_DIR:-"$RUN_DIR/perf_collect/emr_prefetch_${STAMP}_$$"}
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

# Two fixed counters plus four programmable counters are kept in one group so
# every event has an exact, same-window instructions/cycles denominator.
HWPF_EVENTS='{cycles,instructions,cpu/event=0x51,umask=0x20,name=l1d_hwpf_miss/,cpu/event=0x24,umask=0xf0,name=l2_hwpf_all/,cpu/event=0x24,umask=0x30,name=l2_hwpf_miss/,cpu/event=0x26,umask=0x04,name=l2_useless_hwpf/}'
DEMAND_EVENTS='{cycles,instructions,cpu/event=0x25,umask=0x1f,name=l2_lines_in/,cpu/event=0x24,umask=0xe1,name=l2_demand_data_read/,cpu/event=0x24,umask=0x21,name=l2_demand_data_read_miss/,cpu/event=0x21,umask=0x10,name=offcore_l3_miss_demand_data_read/}'
SWPF_EVENTS='{cycles,instructions,cpu/event=0x24,umask=0xc8,name=l2_swpf_hit/,cpu/event=0x24,umask=0x28,name=l2_swpf_miss/,cpu/event=0x4c,umask=0x01,name=load_hit_prefetch_swpf/,cpu/event=0x40,umask=0x0f,name=sw_prefetch_access_any/}'
PRESSURE_EVENTS='{cycles,instructions,cpu/event=0x48,umask=0x01,name=l1d_pending/,cpu/event=0x48,umask=0x01,cmask=0x01,name=l1d_pending_cycles/,cpu/event=0x48,umask=0x02,name=l1d_fb_full_cycles/,cpu/event=0x48,umask=0x04,name=l1d_l2_stall_cycles/}'
OFFCORE_DEMAND_L1D_EVENTS='{cycles,instructions,cpu/event=0x2a,umask=0x01,offcore_rsp=0x10001,name=ocr_demand_data_any/,cpu/event=0x2b,umask=0x01,offcore_rsp=0x10400,name=ocr_hwpf_l1d_any/}'
OFFCORE_L2_DEMAND_L3_EVENTS='{cycles,instructions,cpu/event=0x2a,umask=0x01,offcore_rsp=0x10070,name=ocr_hwpf_l2_any/,cpu/event=0x2b,umask=0x01,offcore_rsp=0x3fbfc00001,name=ocr_demand_data_l3_miss/}'
OFFCORE_L3_EVENTS='{cycles,instructions,cpu/event=0x2a,umask=0x01,offcore_rsp=0x80082380,name=ocr_hwpf_l3_l3_hit/,cpu/event=0x2b,umask=0x01,offcore_rsp=0x94002380,name=ocr_hwpf_l3_l3_miss/}'
SWPF_TYPE_EVENTS='{cycles,instructions,cpu/event=0x40,umask=0x01,name=sw_prefetch_nta/,cpu/event=0x40,umask=0x02,name=sw_prefetch_t0/,cpu/event=0x40,umask=0x04,name=sw_prefetch_t1_t2/,cpu/event=0x40,umask=0x08,name=sw_prefetch_w/}'

PASS_NAMES=(
  01_hw_prefetch
  02_demand_and_lines
  03_software_prefetch
  04_fill_buffer_pressure
  05_offcore_demand_l1d
  06_offcore_l2_demand_l3
  07_offcore_l3
  08_software_prefetch_types
)
PASS_EVENTS=(
  "$HWPF_EVENTS"
  "$DEMAND_EVENTS"
  "$SWPF_EVENTS"
  "$PRESSURE_EVENTS"
  "$OFFCORE_DEMAND_L1D_EVENTS"
  "$OFFCORE_L2_DEMAND_L3_EVENTS"
  "$OFFCORE_L3_EVENTS"
  "$SWPF_TYPE_EVENTS"
)
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
  echo "core_cgroups=$CORE_CGROUPS"
  echo "perf_version=$(perf --version)"
  echo "kernel=$(uname -r)"
  echo "cpu_model=$(lscpu | awk -F: '/Model name/ {sub(/^[[:space:]]+/, "", $2); print $2; exit}')"
} > "$OUTPUT_DIR/config.txt"

FAILURES=0
for index in "${!PASS_NAMES[@]}"; do
  name=${PASS_NAMES[$index]}
  events=${PASS_EVENTS[$index]}
  set +e
  "${SUDO[@]}" perf stat -a -C "$FIRST_CPU" -e "$events" \
    -- sleep "$VALIDATION_SECONDS" > "$OUTPUT_DIR/validate_${name}.txt" 2>&1
  rc=$?
  set -e
  if ((rc != 0)) || grep -q -E '<not counted>|<not supported>' "$OUTPUT_DIR/validate_${name}.txt"; then
    echo "PMU group validation failed: $name" >&2
    FAILURES=$((FAILURES + 1))
  fi
done

if ((FAILURES != 0)); then
  echo "One or more prefetch PMU groups failed validation." >&2
  exit 1
fi

DDR_EVENTS='uncore_imc_0/event=0x05,umask=0xcf,name=imc0_read_cas/,uncore_imc_0/event=0x05,umask=0xf0,name=imc0_write_cas/'
for imc in 1 2 3 4 5 6 7; do
  DDR_EVENTS+=",uncore_imc_${imc}/event=0x05,umask=0xcf,name=imc${imc}_read_cas/"
  DDR_EVENTS+=",uncore_imc_${imc}/event=0x05,umask=0xf0,name=imc${imc}_write_cas/"
done
DDR_SECONDS=$((ROUNDS * ${#PASS_NAMES[@]} * PASS_SECONDS + 5))
"${SUDO[@]}" perf stat -a --per-socket -I "$INTERVAL_MS" -x, \
  -e "$DDR_EVENTS" -- sleep "$DDR_SECONDS" > "$OUTPUT_DIR/ddr_imc.csv" 2>&1 &
DDR_PID=$!

for ((round = 1; round <= ROUNDS; round++)); do
  for index in "${!PASS_NAMES[@]}"; do
    name=${PASS_NAMES[$index]}
    events=${PASS_EVENTS[$index]}
    output="$OUTPUT_DIR/round${round}_${name}.csv"
    printf '%s\t%s\t%s\tstart\t-\n' "$(date --iso-8601=seconds)" "$round" "$name" >> "$TIMELINE"
    set +e
    "${SUDO[@]}" perf stat -a -C "$CPUSET" -A -I "$INTERVAL_MS" -x, \
      -e "$events" --for-each-cgroup "$CORE_CGROUPS" \
      -- sleep "$PASS_SECONDS" > "$output" 2>&1
    rc=$?
    set -e
    printf '%s\t%s\t%s\tend\t%s\n' "$(date --iso-8601=seconds)" "$round" "$name" "$rc" >> "$TIMELINE"
    if ((rc != 0)); then
      FAILURES=$((FAILURES + 1))
    fi
  done
done

set +e
wait "$DDR_PID"
DDR_RC=$?
set -e
if ((DDR_RC != 0)); then
  FAILURES=$((FAILURES + 1))
fi

{
  echo "completed_at=$(date --iso-8601=seconds)"
  echo "failed_passes=$FAILURES"
  echo "ddr_rc=$DDR_RC"
  echo "output_dir=$OUTPUT_DIR"
} > "$OUTPUT_DIR/result.txt"

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
python3 "$SCRIPT_DIR/analyze_emr_prefetch.py" "$OUTPUT_DIR"
cat "$OUTPUT_DIR/result.txt"
if ((FAILURES != 0)); then
  exit 1
fi
