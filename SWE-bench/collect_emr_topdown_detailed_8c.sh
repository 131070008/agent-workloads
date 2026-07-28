#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
RUN_TARGET=${1:-latest}
TOPLEV_PASS_SECONDS=${2:-3}

RUNS_ROOT=${SWE_RUNS_ROOT:-/home/higon/cunzhe/swe_runs}
PMU_TOOLS=${PMU_TOOLS:-/home/higon/cunzhe/tools/pmu-tools}
CPUSET=${PERF_CPUSET:-0-7}
TOPLEV_LEVEL=${PERF_TOPLEV_LEVEL:-6}
WORKLOAD_USER=${SWE_WORKLOAD_USER:-higon}
PASS_FILE=${PERF_SUDO_PASS_FILE:-/home/higon/cunzhe/.secrets/passwd}

if [[ "$RUN_TARGET" == "latest" ]]; then
  RUN_DIR=$(readlink -f "$RUNS_ROOT/fixed_pool_latest")
else
  RUN_DIR=$(readlink -f "$RUN_TARGET")
fi
if [[ ! -d "$RUN_DIR" ]]; then
  echo "Run directory does not exist: $RUN_DIR" >&2
  exit 1
fi
if ! [[ "$TOPLEV_PASS_SECONDS" =~ ^[1-9][0-9]*$ ]]; then
  echo "TOPLEV_PASS_SECONDS must be a positive integer." >&2
  exit 1
fi
if ! [[ "$TOPLEV_LEVEL" =~ ^[1-6]$ ]]; then
  echo "PERF_TOPLEV_LEVEL must be between 1 and 6." >&2
  exit 1
fi
test -x "$PMU_TOOLS/toplev.py"

if [[ -n "${PERF_TOPLEV_CPUSET:-}" ]]; then
  TOPLEV_CPUSET=$PERF_TOPLEV_CPUSET
else
  TOPLEV_CPUSET=$(
    python3 - "$CPUSET" <<'PY'
import pathlib
import sys

def expand(spec):
    values = set()
    for part in spec.split(","):
        if "-" in part:
            start, end = map(int, part.split("-", 1))
            values.update(range(start, end + 1))
        elif part:
            values.add(int(part))
    return values

selected = expand(sys.argv[1])
siblings = set(selected)
for cpu in selected:
    path = pathlib.Path(f"/sys/devices/system/cpu/cpu{cpu}/topology/thread_siblings_list")
    if path.exists():
        siblings.update(expand(path.read_text().strip()))
print(",".join(str(cpu) for cpu in sorted(siblings)))
PY
  )
fi

WORKLOAD_UID=$(getent passwd "$WORKLOAD_USER" | cut -d: -f3)
HOST_CGROUP=${PERF_HOST_CGROUP:-"user.slice/user-${WORKLOAD_UID}.slice/user@${WORKLOAD_UID}.service/swe.slice/swe-agent.slice"}
SANDBOX_CGROUP=${PERF_SANDBOX_CGROUP:-"swe.slice/swe-sandbox.slice"}
SYSTEM_CGROUP=${PERF_SYSTEM_CGROUP:-"system.slice"}
CORE_CGROUPS=${PERF_CORE_CGROUPS:-"$HOST_CGROUP,$SANDBOX_CGROUP,$SYSTEM_CGROUP"}

for cgroup in "$HOST_CGROUP" "$SANDBOX_CGROUP" "$SYSTEM_CGROUP"; do
  test -d "/sys/fs/cgroup/$cgroup"
done

STAMP=$(date +%Y%m%d_%H%M%S)
OUTPUT_DIR=${PERF_TOPDOWN_OUTPUT_DIR:-"$RUN_DIR/perf_collect/emr_topdown_${STAMP}_$$"}
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

TOPDOWN_EVENTS='{cpu/slots/,cpu/topdown-retiring/,cpu/topdown-bad-spec/,cpu/topdown-fe-bound/,cpu/topdown-be-bound/,cpu/topdown-br-mispredict/,cpu/topdown-mem-bound/,cpu/topdown-heavy-ops/,cpu/topdown-fetch-lat/},cpu/event=0xad,umask=0x10,name=int_misc_uop_dropping/'

{
  echo "created_at=$(date --iso-8601=seconds)"
  echo "run_dir=$RUN_DIR"
  echo "output_dir=$OUTPUT_DIR"
  echo "cpuset=$CPUSET"
  echo "toplev_cpuset=$TOPLEV_CPUSET"
  echo "topdown_level=$TOPLEV_LEVEL"
  echo "toplev_pass_seconds=$TOPLEV_PASS_SECONDS"
  echo "host_cgroup=$HOST_CGROUP"
  echo "sandbox_cgroup=$SANDBOX_CGROUP"
  echo "system_cgroup=$SYSTEM_CGROUP"
  echo "cgroup_scope=L1/L2 fixed PERF_METRICS plus INT_MISC.UOP_DROPPING"
  echo "fine_grained_scope=reference only: pmu-tools SPR TMA 5.1 on all tasks scheduled on logical CPUs 0-7"
  echo "formal_formula_scope=Intel EMR metrics v1.4 / TMA 5.2"
  echo "pmu_tools_commit=$(git -C "$PMU_TOOLS" rev-parse HEAD)"
} > "$OUTPUT_DIR/config.txt"

cat > "$OUTPUT_DIR/PMUTOOLS_REFERENCE_ONLY.txt" <<'EOF'
The bundled pmu-tools spr_server_ratios.py is SPR TMA 5.1.
Its L3-L6 output is reference-only on this Emerald Rapids system.
Use the pinned Intel EMR metrics v1.4 / TMA 5.2 manifest for formal formulas.
EOF
echo "WARNING: pmu-tools L3-L6 output is SPR TMA 5.1 reference-only on EMR." >&2

set +e
"${SUDO[@]}" perf stat -a -C "$CPUSET" -A -x, \
  -e "$TOPDOWN_EVENTS" --for-each-cgroup "$CORE_CGROUPS" \
  -- sleep "$TOPLEV_PASS_SECONDS" \
  > "$OUTPUT_DIR/cgroup_l1_l2_raw.csv" 2>&1
CGROUP_RC=$?
CGROUP_SUMMARY_RC=0
if ((CGROUP_RC == 0)); then
  python3 "$SCRIPT_DIR/summarize_emr_topdown_l1_l2.py" \
    --input "$OUTPUT_DIR/cgroup_l1_l2_raw.csv" \
    --output-csv "$OUTPUT_DIR/cgroup_l1_l2_metrics.csv" \
    --output-text "$OUTPUT_DIR/cgroup_l1_l2_readable.txt"
  CGROUP_SUMMARY_RC=$?
fi

"$PMU_TOOLS/toplev.py" -l"$TOPLEV_LEVEL" \
  --no-multiplex --no-uncore --verbose --no-desc -x, \
  -C "$TOPLEV_CPUSET" sleep "$TOPLEV_PASS_SECONDS" \
  > "$OUTPUT_DIR/pool_0_7_l${TOPLEV_LEVEL}.csv" 2>&1
TOPLEV_RC=$?
set -e

grep -E '<not supported>|Traceback|No permission|Access to performance' \
  "$OUTPUT_DIR/cgroup_l1_l2_raw.csv" \
  > "$OUTPUT_DIR/cgroup_errors.txt" 2>/dev/null || true
grep -E '<not supported>|Traceback|No permission|Access to performance' \
  "$OUTPUT_DIR/pool_0_7_l${TOPLEV_LEVEL}.csv" \
  > "$OUTPUT_DIR/toplev_errors.txt" 2>/dev/null || true
grep -E 'event not found' \
  "$OUTPUT_DIR/pool_0_7_l${TOPLEV_LEVEL}.csv" \
  > "$OUTPUT_DIR/model_event_warnings.txt" 2>/dev/null || true
awk -F, '$7 ~ /^[0-9]+([.][0-9]+)?$/ {print $7}' \
  "$OUTPUT_DIR/cgroup_l1_l2_raw.csv" | sort -nu \
  > "$OUTPUT_DIR/cgroup_running_percentages.txt"

FAILED=0
if ((CGROUP_RC != 0)) || ((CGROUP_SUMMARY_RC != 0)) || [[ -s "$OUTPUT_DIR/cgroup_errors.txt" ]]; then
  FAILED=$((FAILED + 1))
fi
if ((TOPLEV_RC != 0)) || [[ -s "$OUTPUT_DIR/toplev_errors.txt" ]]; then
  FAILED=$((FAILED + 1))
fi

{
  echo "completed_at=$(date --iso-8601=seconds)"
  echo "cgroup_l1_l2_rc=$CGROUP_RC"
  echo "cgroup_l1_l2_summary_rc=$CGROUP_SUMMARY_RC"
  echo "pool_l${TOPLEV_LEVEL}_rc=$TOPLEV_RC"
  echo "failed_steps=$FAILED"
  echo "cgroup_running_percentages=$(paste -sd, "$OUTPUT_DIR/cgroup_running_percentages.txt")"
  echo "model_event_warning_lines=$(wc -l < "$OUTPUT_DIR/model_event_warnings.txt")"
  echo "output_dir=$OUTPUT_DIR"
} > "$OUTPUT_DIR/result.txt"

cat "$OUTPUT_DIR/result.txt"
if ((FAILED != 0)); then
  exit 1
fi
