#!/usr/bin/env bash
set -euo pipefail

RUNNER=${SWE_FIXED_POOL_RUNNER:-/home/higon/cunzhe/swe_runs/run_fixed_pool_96_8c.sh}
STOPPER=${SWE_FIXED_POOL_STOPPER:-/home/higon/cunzhe/swe_runs/stop_fixed_pool_8c.sh}
ANALYZER=${SWE_FAULT_NETWORK_ANALYZER:-/home/higon/cunzhe/agent-workloads/SWE-bench/analyze_fault_network.py}
PASS_FILE=${PERF_SUDO_PASS_FILE:-/home/higon/cunzhe/.secrets/passwd}
MODEL_ENV=${SWE_MODEL_ENV:-/home/higon/cunzhe/.secrets/deepseek.env}
WORKLOAD_USER=${SWE_WORKLOAD_USER:-higon}

DURATION_SECONDS=${SWE_RETEST_DURATION_SECONDS:-360}
CONCURRENCY=${SWE_RETEST_CONCURRENCY:-96}
START_GAP_SECONDS=${SWE_RETEST_START_GAP_SECONDS:-1}
TARGET_CONTAINERS=${SWE_RETEST_TARGET_CONTAINERS:-88}
STABLE_SAMPLES=${SWE_RETEST_STABLE_SAMPLES:-3}
READY_TIMEOUT_SECONDS=${SWE_RETEST_READY_TIMEOUT_SECONDS:-240}
CAPTURE_SECONDS=${SWE_RETEST_CAPTURE_SECONDS:-60}
CPUSET=${SWE_RETEST_CPUSET:-0-7}
INTERFACE=${SWE_RETEST_INTERFACE:-ens16f0}
SNAPLEN=${SWE_RETEST_SNAPLEN:-96}

if [[ ! -r "$MODEL_ENV" ]]; then
  echo "Model environment is not readable: $MODEL_ENV" >&2
  exit 1
fi

set -a
source "$MODEL_ENV"
set +a

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

if docker ps --format '{{.Names}}' | grep -q '^minisweagent-'; then
  echo "Refusing to start: minisweagent containers are already running." >&2
  exit 1
fi

LAUNCH_OUTPUT=$("$RUNNER" "$DURATION_SECONDS" "$CONCURRENCY" "$START_GAP_SECONDS")
RUN_DIR=$(printf '%s\n' "$LAUNCH_OUTPUT" | awk -F= '/^RUN_DIR=/ {print $2; exit}')
if [[ -z "$RUN_DIR" || ! -d "$RUN_DIR" ]]; then
  echo "Could not resolve fixed-pool RUN_DIR." >&2
  printf '%s\n' "$LAUNCH_OUTPUT" >&2
  exit 1
fi

STATUS_FILE="$RUN_DIR/fault_network_status.txt"
READY_LOG="$RUN_DIR/fault_network_readiness.tsv"
DATA_DIR="$RUN_DIR/perf_collect/fault_network"
mkdir -p "$DATA_DIR"
printf 'timestamp\tactive_jobs\tcontainers\tstable_samples\terror_logs\n' > "$READY_LOG"

stop_workload() {
  "$STOPPER" "$RUN_DIR" > "$RUN_DIR/fault_network_stop.log" 2>&1 || true
}
trap stop_workload EXIT

{
  echo "state=warming_up"
  echo "started_at=$(date --iso-8601=seconds)"
  echo "run_dir=$RUN_DIR"
  echo "concurrency=$CONCURRENCY"
  echo "capture_seconds=$CAPTURE_SECONDS"
  echo "interface=$INTERFACE"
  echo "snaplen=$SNAPLEN"
} > "$STATUS_FILE"

deadline=$((SECONDS + READY_TIMEOUT_SECONDS))
stable=0
while ((SECONDS < deadline)); do
  active_jobs=$(tail -n 1 "$RUN_DIR/meta/heartbeat.log" 2>/dev/null | sed -n 's/.*active_jobs=\([0-9][0-9]*\).*/\1/p' || true)
  active_jobs=${active_jobs:-0}
  containers=$(docker ps --format '{{.Names}}' | grep -c '^minisweagent-' || true)
  error_logs=$(grep -RIl -E 'insufficient.balance|余额不足|authentication.failed|Missing credentials|rate.limit|429 Too Many Requests' "$RUN_DIR/logs" 2>/dev/null | wc -l || true)

  if ((error_logs >= 12)); then
    echo "state=aborted_api_errors" >> "$STATUS_FILE"
    echo "error_logs=$error_logs" >> "$STATUS_FILE"
    exit 1
  fi
  if ((active_jobs >= CONCURRENCY && containers >= TARGET_CONTAINERS)); then
    stable=$((stable + 1))
  else
    stable=0
  fi
  printf '%s\t%s\t%s\t%s\t%s\n' \
    "$(date --iso-8601=seconds)" "$active_jobs" "$containers" "$stable" "$error_logs" \
    >> "$READY_LOG"
  if ((stable >= STABLE_SAMPLES)); then
    break
  fi
  sleep 5
done

if ((stable < STABLE_SAMPLES)); then
  echo "state=aborted_not_ready" >> "$STATUS_FILE"
  exit 1
fi

WORKLOAD_UID=$(id -u "$WORKLOAD_USER")
HOST_CGROUP="user.slice/user-${WORKLOAD_UID}.slice/user@${WORKLOAD_UID}.service/swe.slice/swe-agent.slice"
SANDBOX_CGROUP="swe.slice/swe-sandbox.slice"
SYSTEM_CGROUP="system.slice"
CORE_CGROUPS="$HOST_CGROUP,$SANDBOX_CGROUP,$SYSTEM_CGROUP"

{
  echo "state=collecting"
  echo "ready_at=$(date --iso-8601=seconds)"
  echo "ready_active_jobs=$active_jobs"
  echo "ready_containers=$containers"
  echo "cgroups=$CORE_CGROUPS"
} >> "$STATUS_FILE"

ethtool -k "$INTERFACE" > "$DATA_DIR/ethtool_features.txt" 2>&1 || true
ethtool -S "$INTERFACE" > "$DATA_DIR/ethtool_stats_before.txt" 2>&1 || true

"${SUDO[@]}" timeout --preserve-status --signal=INT --kill-after=5 \
  "$CAPTURE_SECONDS" tcpdump -i "$INTERFACE" -Q in -nn -B 4096 -s "$SNAPLEN" \
  -w "$DATA_DIR/rx.pcap" > "$DATA_DIR/rx_tcpdump.log" 2>&1 &
RX_PID=$!

"${SUDO[@]}" timeout --preserve-status --signal=INT --kill-after=5 \
  "$CAPTURE_SECONDS" tcpdump -i "$INTERFACE" -Q out -nn -B 4096 -s "$SNAPLEN" \
  -w "$DATA_DIR/tx.pcap" > "$DATA_DIR/tx_tcpdump.log" 2>&1 &
TX_PID=$!

sar -n DEV 1 "$CAPTURE_SECONDS" > "$DATA_DIR/network_sar.log" 2>&1 &
SAR_PID=$!

"${SUDO[@]}" perf stat -a -C "$CPUSET" -A -I 1000 -x, \
  -e page-faults,minor-faults,major-faults \
  --for-each-cgroup "$CORE_CGROUPS" \
  -- sleep "$CAPTURE_SECONDS" > "$DATA_DIR/faults_by_cgroup.csv" 2>&1 &
PERF_PID=$!

set +e
wait "$PERF_PID"; PERF_RC=$?
wait "$RX_PID"; RX_RC=$?
wait "$TX_PID"; TX_RC=$?
wait "$SAR_PID"; SAR_RC=$?
set -e

ethtool -S "$INTERFACE" > "$DATA_DIR/ethtool_stats_after.txt" 2>&1 || true
"${SUDO[@]}" chown -R "$WORKLOAD_USER:$WORKLOAD_USER" "$DATA_DIR" 2>/dev/null || true

{
  echo "collection_completed_at=$(date --iso-8601=seconds)"
  echo "perf_rc=$PERF_RC"
  echo "rx_tcpdump_rc=$RX_RC"
  echo "tx_tcpdump_rc=$TX_RC"
  echo "sar_rc=$SAR_RC"
  echo "state=stopping"
} >> "$STATUS_FILE"

stop_workload
trap - EXIT

{
  echo "stopped_at=$(date --iso-8601=seconds)"
  echo "remaining_minisweagent_containers=$(docker ps --format '{{.Names}}' | grep -c '^minisweagent-' || true)"
  echo "state=analyzing"
} >> "$STATUS_FILE"

set +e
python3 "$ANALYZER" "$RUN_DIR" > "$RUN_DIR/fault_network_analysis.log" 2>&1
ANALYZER_RC=$?
set -e
{
  echo "analyzer_rc=$ANALYZER_RC"
  echo "state=complete"
} >> "$STATUS_FILE"

cat "$STATUS_FILE"
if [[ -f "$RUN_DIR/fault_network_summary.md" ]]; then
  cat "$RUN_DIR/fault_network_summary.md"
fi
