#!/usr/bin/env bash
set -euo pipefail

CUNZHE_ROOT=${CUNZHE_ROOT:-/home/higon/cunzhe}
WORKLOAD_ROOT=$CUNZHE_ROOT/agent-workloads
GOLDEN_DIR=${SWE_GOLDEN_DIR:-$CUNZHE_ROOT/swe_runs/golden_replay/flash}
CPUSET=${SWE_CPUSET:-0-7}
STAMP=$(date +%Y%m%d_%H%M%S)
HOST_TAG=$(hostname -s | tr -c 'A-Za-z0-9_.-' '_')
OUTPUT_ROOT=${SWE_OUTPUT_ROOT:-$CUNZHE_ROOT/swe_runs/golden_lifecycle_30_${HOST_TAG}_${STAMP}}

test -x "$WORKLOAD_ROOT/.venv-swe/bin/python"
test -f "$GOLDEN_DIR/manifest.json"
test -x "$WORKLOAD_ROOT/SWE-bench/run_swe_golden_fixed_sweep.sh"
docker info >/dev/null
if [[ -n "$(docker ps -q)" && "${ALLOW_RUNNING_CONTAINERS:-0}" != 1 ]]; then
  echo 'ERROR: running containers detected; use an idle host for comparable results.' >&2
  docker ps
  exit 1
fi

mkdir -p "$OUTPUT_ROOT"
{
  date -Iseconds
  hostname
  uptime
  uname -a
  cat /proc/cmdline
  lscpu
  lscpu -e=CPU,NODE,SOCKET,CORE,ONLINE,MAXMHZ,MINMHZ \
    | awk 'NR == 1 || ($1 ~ /^[0-9]+$/ && $1 >= 0 && $1 <= 7)'
  if [[ -r /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor ]]; then
    printf 'cpu0_scaling_governor='
    cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor
  fi
  free -h
  docker version
  docker info --format 'driver={{.Driver}} cgroup={{.CgroupDriver}} version={{.CgroupVersion}} root={{.DockerRootDir}}'
} > "$OUTPUT_ROOT/platform_before.txt" 2>&1

export SWE_GOLDEN_DIR="$GOLDEN_DIR"
export SWE_OUTPUT_ROOT="$OUTPUT_ROOT"
export SWE_WORKER_SWEEP='1 16'
export SWE_REPEATS=1
export SWE_PRIMARY_CONCURRENCY=k16
export SWE_CPUSET="$CPUSET"

echo "OUTPUT_ROOT=$OUTPUT_ROOT"
set +e
"$WORKLOAD_ROOT/SWE-bench/run_swe_golden_fixed_sweep.sh" \
  2>&1 | tee "$OUTPUT_ROOT/controller.log"
runner_rc=${PIPESTATUS[0]}
set -e

printf '%s\n' "$runner_rc" > "$OUTPUT_ROOT/controller_returncode.txt"
date -Iseconds > "$OUTPUT_ROOT/finished_at"
docker ps --no-trunc > "$OUTPUT_ROOT/docker_ps_after.txt"

for mode in k1 k16; do
  test -f "$OUTPUT_ROOT/$mode/performance_summary.json"
  test -f "$OUTPUT_ROOT/$mode/runner_returncode.txt"
done
test "$runner_rc" -eq 0
test -z "$(docker ps -q)"

touch "$OUTPUT_ROOT/COMPLETE"
echo "Golden replay complete: $OUTPUT_ROOT"
