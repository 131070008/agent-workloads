#!/usr/bin/env bash
set -euo pipefail

DATA_ROOT=${DATA_ROOT:-/data/cunzhe}
CPU_CORE=${CPU_CORE:-2}
REPO_ROOT=${REPO_ROOT:-$DATA_ROOT/agent-workloads}
CASE_IDS=${CASE_IDS:-}
CASE_TIMEOUT_SECONDS=${CASE_TIMEOUT_SECONDS:-1800}
TIMESTAMP=${TIMESTAMP:-$(date +%Y%m%d_%H%M%S)}
RUN_DIR=${RUN_DIR:-$DATA_ROOT/swe_runs/aws36_golden_single_cpu${CPU_CORE}_$(hostname -s)_$TIMESTAMP}

command -v taskset >/dev/null
[[ "$CPU_CORE" =~ ^[0-9]+$ ]] || { echo "CPU_CORE must be one logical CPU number" >&2; exit 2; }
[[ -d "/sys/devices/system/cpu/cpu$CPU_CORE" ]] || { echo "CPU $CPU_CORE does not exist" >&2; exit 2; }
taskset --cpu-list "$CPU_CORE" true
SIBLINGS=$(cat "/sys/devices/system/cpu/cpu$CPU_CORE/topology/thread_siblings_list")

echo "CPU_CORE=$CPU_CORE"
echo "THREAD_SIBLINGS=$SIBLINGS"
echo "Agent affinity: CPU $CPU_CORE"
echo "Sandbox affinity: CPU $CPU_CORE"
echo "CASE_TIMEOUT_SECONDS=$CASE_TIMEOUT_SECONDS"
echo "RUN_DIR=$RUN_DIR"

DATA_ROOT="$DATA_ROOT" \
REPO_ROOT="$REPO_ROOT" \
SWE_CPUSET="$CPU_CORE" \
CASE_IDS="$CASE_IDS" \
CASE_TIMEOUT_SECONDS="$CASE_TIMEOUT_SECONDS" \
RUN_DIR="$RUN_DIR" \
  "$REPO_ROOT/SWE-bench/reproduction/16_run_aws36_golden.sh"
