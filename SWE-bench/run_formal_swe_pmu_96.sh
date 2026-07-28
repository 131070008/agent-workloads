#!/usr/bin/env bash
set -euo pipefail

RUNNER=${SWE_FIXED_POOL_RUNNER:-/home/higon/cunzhe/swe_runs/run_fixed_pool_96_8c.sh}
STOPPER=${SWE_FIXED_POOL_STOPPER:-/home/higon/cunzhe/swe_runs/stop_fixed_pool_8c.sh}
COLLECTOR=${SWE_PMU_COLLECTOR:-/home/higon/cunzhe/agent-workloads/SWE-bench/collect_emr_pmu_8c.sh}
ANALYZER=${SWE_PMU_ANALYZER:-/home/higon/cunzhe/agent-workloads/SWE-bench/analyze_formal_swe_pmu.py}
RUNS_ROOT=${SWE_RUNS_ROOT:-/home/higon/cunzhe/swe_runs}
PASS_FILE=${PERF_SUDO_PASS_FILE:-/home/higon/cunzhe/.secrets/passwd}
MODEL_ENV=${SWE_MODEL_ENV:-/home/higon/cunzhe/.secrets/deepseek.env}
WORKLOAD_USER=${SWE_WORKLOAD_USER:-higon}

DURATION_SECONDS=${SWE_FORMAL_DURATION_SECONDS:-600}
CONCURRENCY=${SWE_FORMAL_CONCURRENCY:-96}
START_GAP_SECONDS=${SWE_FORMAL_START_GAP_SECONDS:-1}
TARGET_CONTAINERS=${SWE_FORMAL_TARGET_CONTAINERS:-88}
STABLE_SAMPLES=${SWE_FORMAL_STABLE_SAMPLES:-3}
READY_TIMEOUT_SECONDS=${SWE_FORMAL_READY_TIMEOUT_SECONDS:-210}
PASS_SECONDS=${PERF_PASS_SECONDS:-10}
ROUNDS=${PERF_ROUNDS:-3}
PMU_PASS_COUNT=${SWE_PMU_PASS_COUNT:-9}
SCHED_SECONDS=${PERF_SCHED_SECONDS:-30}
COMM_SAMPLE_SECONDS=${PERF_COMM_SAMPLE_SECONDS:-30}
SAR_SECONDS=$((PASS_SECONDS * PMU_PASS_COUNT * ROUNDS + 5))

if [[ ! -r "$MODEL_ENV" ]]; then
  echo "Model environment is not readable: $MODEL_ENV" >&2
  exit 1
fi

set -a
source "$MODEL_ENV"
set +a
REQUESTED_MODEL=${SWE_MODEL:-openai/deepseek-chat}
export REQUESTED_MODEL

# Fail before launching 96 agents if the key, endpoint, or model is unusable.
# The output deliberately contains no credential or prompt content.
PREFLIGHT_OUTPUT=$(
  python3 - <<'PY'
import json
import os
import sys
import urllib.error
import urllib.request

base = os.environ.get("OPENAI_API_BASE", "").rstrip("/")
key = os.environ.get("OPENAI_API_KEY", "")
model = os.environ.get("REQUESTED_MODEL", "openai/deepseek-chat")
if model.startswith("openai/"):
    model = model.removeprefix("openai/")
if not base or not key:
    raise SystemExit("API preflight failed: OPENAI_API_BASE or OPENAI_API_KEY is missing")

payload = json.dumps({
    "model": model,
    "messages": [{"role": "user", "content": "ping"}],
    "max_tokens": 1,
    "stream": False,
}).encode("utf-8")
request = urllib.request.Request(
    f"{base}/chat/completions",
    data=payload,
    headers={
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    },
)
try:
    with urllib.request.urlopen(request, timeout=30) as response:
        data = json.load(response)
except urllib.error.HTTPError as error:
    detail = error.read().decode("utf-8", errors="replace")[:500]
    raise SystemExit(f"API preflight failed: HTTP {error.code}: {detail}") from error
except Exception as error:
    raise SystemExit(f"API preflight failed: {error}") from error
if "error" in data:
    raise SystemExit(f"API preflight failed: {data['error']}")
usage = data.get("usage", {})
print(f"response_model={data.get('model', 'unknown')}")
print(f"total_tokens={int(usage.get('total_tokens', 0) or 0)}")
PY
)
PREFLIGHT_MODEL=$(printf '%s\n' "$PREFLIGHT_OUTPUT" | sed -n 's/^response_model=//p')
PREFLIGHT_TOKENS=$(printf '%s\n' "$PREFLIGHT_OUTPUT" | sed -n 's/^total_tokens=//p')

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

LAUNCH_OUTPUT=$(
  "$RUNNER" "$DURATION_SECONDS" "$CONCURRENCY" "$START_GAP_SECONDS"
)
RUN_DIR=$(printf '%s\n' "$LAUNCH_OUTPUT" | awk -F= '/^RUN_DIR=/ {print $2; exit}')
if [[ -z "$RUN_DIR" || ! -d "$RUN_DIR" ]]; then
  echo "Could not resolve fixed-pool RUN_DIR." >&2
  printf '%s\n' "$LAUNCH_OUTPUT" >&2
  exit 1
fi

printf '%s\n' "$LAUNCH_OUTPUT" > "$RUN_DIR/formal_launch.txt"
STATUS_FILE="$RUN_DIR/formal_status.txt"
READY_LOG="$RUN_DIR/formal_readiness.tsv"
printf 'timestamp\tactive_jobs\tcontainers\tstable_samples\terror_logs\n' > "$READY_LOG"

stop_workload() {
  "$STOPPER" "$RUN_DIR" > "$RUN_DIR/formal_stop.log" 2>&1 || true
}
trap stop_workload EXIT

{
  echo "formal_experiment=true"
  echo "supervisor_pid=$$"
  echo "started_at=$(date --iso-8601=seconds)"
  echo "run_dir=$RUN_DIR"
  echo "requested_model=$REQUESTED_MODEL"
  echo "preflight_response_model=$PREFLIGHT_MODEL"
  echo "preflight_total_tokens=${PREFLIGHT_TOKENS:-0}"
  echo "duration_seconds=$DURATION_SECONDS"
  echo "concurrency=$CONCURRENCY"
  echo "target_containers=$TARGET_CONTAINERS"
  echo "stable_samples=$STABLE_SAMPLES"
  echo "pass_seconds=$PASS_SECONDS"
  echo "pmu_passes_per_round=$PMU_PASS_COUNT"
  echo "pmu_rounds=$ROUNDS"
  echo "sched_seconds=$SCHED_SECONDS"
  echo "comm_sample_seconds=$COMM_SAMPLE_SECONDS"
  echo "state=warming_up"
} > "$STATUS_FILE"

deadline=$((SECONDS + READY_TIMEOUT_SECONDS))
stable=0
while ((SECONDS < deadline)); do
  active_jobs=$(tail -n 1 "$RUN_DIR/meta/heartbeat.log" 2>/dev/null | sed -n 's/.*active_jobs=\([0-9][0-9]*\).*/\1/p' || true)
  active_jobs=${active_jobs:-0}
  containers=$(docker ps --format '{{.Names}}' | grep -c '^minisweagent-' || true)
  error_logs=$(grep -RIl -E 'insufficient.balance|余额不足|authentication.failed|Missing credentials|rate.limit|429 Too Many Requests' "$RUN_DIR/logs" 2>/dev/null | wc -l || true)

  if ((error_logs >= 12)); then
    echo "Too many API/auth/rate-limit error logs: $error_logs" >> "$STATUS_FILE"
    echo "state=aborted_api_errors" >> "$STATUS_FILE"
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
  echo "The fixed pool did not become stable before timeout." >> "$STATUS_FILE"
  exit 1
fi

{
  echo "ready_at=$(date --iso-8601=seconds)"
  echo "ready_active_jobs=$active_jobs"
  echo "ready_containers=$containers"
  echo "state=collecting"
} >> "$STATUS_FILE"

PERF_DIR="$RUN_DIR/perf_collect/formal"
mkdir -p "$PERF_DIR"

"${SUDO[@]}" perf sched record -a -C 0-7 \
  -o "$PERF_DIR/perf_sched_0_7_${SCHED_SECONDS}s.data" \
  -- sleep "$SCHED_SECONDS" \
  > "$PERF_DIR/perf_sched.log" 2>&1 &
SCHED_PID=$!
echo "$SCHED_PID" > "$RUN_DIR/perf_sched.pid"

"${SUDO[@]}" perf record -a -C 0-7 -F 99 -e cpu-clock --all-cgroups \
  -o "$PERF_DIR/perf_cgroup_comm_0_7_${COMM_SAMPLE_SECONDS}s.data" \
  -- sleep "$COMM_SAMPLE_SECONDS" \
  > "$PERF_DIR/perf_cgroup_comm.log" 2>&1 &
COMM_SAMPLE_PID=$!
echo "$COMM_SAMPLE_PID" > "$RUN_DIR/perf_cgroup_comm.pid"

sar -n DEV 1 "$SAR_SECONDS" \
  > "$PERF_DIR/network_sar.log" 2>&1 &
SAR_PID=$!
echo "$SAR_PID" > "$RUN_DIR/network_sar.pid"

PERF_OUTPUT_DIR="$PERF_DIR/pmu" \
  "$COLLECTOR" "$RUN_DIR" "$PASS_SECONDS" "$ROUNDS" \
  > "$PERF_DIR/collector.log" 2>&1 || COLLECTOR_RC=$?
COLLECTOR_RC=${COLLECTOR_RC:-0}
if ((COLLECTOR_RC != 0)); then
  kill "$SAR_PID" 2>/dev/null || true
  kill "$COMM_SAMPLE_PID" 2>/dev/null || true
fi

set +e
wait "$SCHED_PID"
SCHED_RC=$?
wait "$COMM_SAMPLE_PID"
COMM_SAMPLE_RC=$?
wait "$SAR_PID"
SAR_RC=$?
set -e
"${SUDO[@]}" chown "$WORKLOAD_USER:$WORKLOAD_USER" \
  "$PERF_DIR/perf_sched_0_7_${SCHED_SECONDS}s.data" \
  "$PERF_DIR/perf_sched.log" \
  "$PERF_DIR/perf_cgroup_comm_0_7_${COMM_SAMPLE_SECONDS}s.data" \
  "$PERF_DIR/perf_cgroup_comm.log" 2>/dev/null || true

SCHED_DATA="$PERF_DIR/perf_sched_0_7_${SCHED_SECONDS}s.data"
set +e
perf sched latency -i "$SCHED_DATA" --sort runtime \
  > "$PERF_DIR/perf_sched_latency_0_7.txt" 2>&1
SCHED_REPORT_RC=$?
perf sched latency -i "$SCHED_DATA" -C 0 --sort runtime \
  > "$PERF_DIR/perf_sched_latency_cpu0.txt" 2>&1
SCHED_CPU0_REPORT_RC=$?
perf report \
  -i "$PERF_DIR/perf_cgroup_comm_0_7_${COMM_SAMPLE_SECONDS}s.data" \
  --stdio --sort cgroup,comm --no-children --percent-limit 0 \
  > "$PERF_DIR/perf_cgroup_comm_report.txt" 2>&1
COMM_REPORT_RC=$?
set -e

{
  echo "collection_completed_at=$(date --iso-8601=seconds)"
  echo "collector_rc=$COLLECTOR_RC"
  echo "sched_rc=$SCHED_RC"
  echo "comm_sample_rc=$COMM_SAMPLE_RC"
  echo "comm_report_rc=$COMM_REPORT_RC"
  echo "sched_report_rc=$SCHED_REPORT_RC"
  echo "sched_cpu0_report_rc=$SCHED_CPU0_REPORT_RC"
  echo "sar_rc=$SAR_RC"
  echo "completed_jobs=$(grep -c ' finish ' "$RUN_DIR/meta/events.log" 2>/dev/null || true)"
  echo "launched_jobs=$(grep -c ' launch ' "$RUN_DIR/meta/events.log" 2>/dev/null || true)"
  echo "state=stopping"
} >> "$STATUS_FILE"

stop_workload
trap - EXIT

{
  echo "stopped_at=$(date --iso-8601=seconds)"
  echo "remaining_minisweagent_containers=$(docker ps --format '{{.Names}}' | grep -c '^minisweagent-' || true)"
  echo "state=complete"
} >> "$STATUS_FILE"

set +e
python3 "$ANALYZER" "$RUN_DIR" > "$RUN_DIR/formal_analysis.log" 2>&1
ANALYZER_RC=$?
set -e
echo "analyzer_rc=$ANALYZER_RC" >> "$STATUS_FILE"

cat "$STATUS_FILE"
