#!/usr/bin/env bash
set -euo pipefail

RUNNER=${SWE_FIXED_POOL_RUNNER:-/home/higon/cunzhe/swe_runs/run_fixed_pool_96_8c.sh}
STOPPER=${SWE_FIXED_POOL_STOPPER:-/home/higon/cunzhe/swe_runs/stop_fixed_pool_8c.sh}
COLLECTOR=${SWE_PMU_COLLECTOR:-/home/higon/cunzhe/agent-workloads/SWE-bench/collect_emr_pmu_detailed_8c.sh}
RUNS_ROOT=${SWE_RUNS_ROOT:-/home/higon/cunzhe/swe_runs}
MODEL_ENV=${SWE_MODEL_ENV:-/home/higon/cunzhe/.secrets/deepseek.env}

DURATION_SECONDS=${SWE_FORMAL_DURATION_SECONDS:-1200}
CONCURRENCY=${SWE_FORMAL_CONCURRENCY:-96}
START_GAP_SECONDS=${SWE_FORMAL_START_GAP_SECONDS:-1}
TARGET_CONTAINERS=${SWE_FORMAL_TARGET_CONTAINERS:-88}
STABLE_SAMPLES=${SWE_FORMAL_STABLE_SAMPLES:-3}
READY_TIMEOUT_SECONDS=${SWE_FORMAL_READY_TIMEOUT_SECONDS:-240}
RAW_PASS_SECONDS=${PERF_RAW_PASS_SECONDS:-5}
TOPLEV_PASS_SECONDS=${PERF_TOPLEV_PASS_SECONDS:-3}

if [[ ! -r "$MODEL_ENV" ]]; then
  echo "Model environment is not readable: $MODEL_ENV" >&2
  exit 1
fi
test -x "$RUNNER"
test -x "$STOPPER"
test -x "$COLLECTOR"

set -a
source "$MODEL_ENV"
set +a
REQUESTED_MODEL=${SWE_MODEL:-openai/deepseek-chat}
export REQUESTED_MODEL

PREFLIGHT_OUTPUT=$(
  python3 - <<'PY'
import json
import os
import urllib.error
import urllib.request

base = os.environ.get("OPENAI_API_BASE", "").rstrip("/")
key = os.environ.get("OPENAI_API_KEY", "")
model = os.environ.get("REQUESTED_MODEL", "openai/deepseek-chat")
if model.startswith("openai/"):
    model = model.removeprefix("openai/")
if not base or not key:
    raise SystemExit("API preflight failed: endpoint or key is missing")

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

printf '%s\n' "$LAUNCH_OUTPUT" > "$RUN_DIR/formal_detailed_launch.txt"
STATUS_FILE="$RUN_DIR/formal_detailed_status.txt"
READY_LOG="$RUN_DIR/formal_detailed_readiness.tsv"
MONITOR_LOG="$RUN_DIR/formal_detailed_monitor.tsv"
printf 'timestamp\tactive_jobs\tcontainers\tstable_samples\terror_logs\n' > "$READY_LOG"
printf 'timestamp\tactive_jobs\tcontainers\tcpu_busy_percent\terror_logs\n' > "$MONITOR_LOG"

stop_workload() {
  "$STOPPER" "$RUN_DIR" > "$RUN_DIR/formal_detailed_stop.log" 2>&1 || true
}
trap stop_workload EXIT

{
  echo "formal_detailed_experiment=true"
  echo "started_at=$(date --iso-8601=seconds)"
  echo "run_dir=$RUN_DIR"
  echo "requested_model=$REQUESTED_MODEL"
  echo "preflight_response_model=$PREFLIGHT_MODEL"
  echo "preflight_total_tokens=${PREFLIGHT_TOKENS:-0}"
  echo "duration_seconds=$DURATION_SECONDS"
  echo "concurrency=$CONCURRENCY"
  echo "agent_cpuset=0-7"
  echo "sandbox_cpuset=0-7"
  echo "target_containers=$TARGET_CONTAINERS"
  echo "raw_pass_seconds=$RAW_PASS_SECONDS"
  echo "toplev_pass_seconds=$TOPLEV_PASS_SECONDS"
  echo "state=warming_up"
} > "$STATUS_FILE"

deadline=$((SECONDS + READY_TIMEOUT_SECONDS))
stable=0
while ((SECONDS < deadline)); do
  active_jobs=$(tail -n 1 "$RUN_DIR/meta/heartbeat.log" 2>/dev/null |
    sed -n 's/.*active_jobs=\([0-9][0-9]*\).*/\1/p' || true)
  active_jobs=${active_jobs:-0}
  containers=$(docker ps --format '{{.Names}}' | grep -c '^minisweagent-' || true)
  error_logs=$(grep -RIl -E \
    'insufficient.balance|余额不足|authentication.failed|Missing credentials|rate.limit|429 Too Many Requests' \
    "$RUN_DIR/logs" 2>/dev/null | wc -l || true)

  if ((error_logs >= 12)); then
    echo "state=aborted_api_errors" >> "$STATUS_FILE"
    echo "api_error_logs=$error_logs" >> "$STATUS_FILE"
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

{
  echo "ready_at=$(date --iso-8601=seconds)"
  echo "ready_active_jobs=$active_jobs"
  echo "ready_containers=$containers"
  echo "state=collecting"
} >> "$STATUS_FILE"

monitor_workload() {
  while true; do
    active=$(tail -n 1 "$RUN_DIR/meta/heartbeat.log" 2>/dev/null |
      sed -n 's/.*active_jobs=\([0-9][0-9]*\).*/\1/p' || true)
    active=${active:-0}
    running=$(docker ps --format '{{.Names}}' | grep -c '^minisweagent-' || true)
    errors=$(grep -RIl -E \
      'insufficient.balance|余额不足|authentication.failed|Missing credentials|rate.limit|429 Too Many Requests' \
      "$RUN_DIR/logs" 2>/dev/null | wc -l || true)
    busy=$(S_TIME_FORMAT=ISO mpstat -P 0-7 1 1 2>/dev/null |
      awk '$1 == "Average:" && $2 ~ /^[0-7]$/ {
        sum += 100 - $NF
        count++
      }
      END {
        if (count) printf "%.2f", sum / count
        else print "NA"
      }')
    printf '%s\t%s\t%s\t%s\t%s\n' \
      "$(date --iso-8601=seconds)" "$active" "$running" "$busy" "$errors" \
      >> "$MONITOR_LOG"
    sleep 4
  done
}
monitor_workload &
MONITOR_PID=$!

PERF_DIR="$RUN_DIR/perf_collect/formal_detailed"
mkdir -p "$PERF_DIR"
set +e
PERF_OUTPUT_DIR="$PERF_DIR" \
  "$COLLECTOR" "$RUN_DIR" "$RAW_PASS_SECONDS" "$TOPLEV_PASS_SECONDS" \
  > "$RUN_DIR/formal_detailed_collector.log" 2>&1
COLLECTOR_RC=$?
set -e

kill "$MONITOR_PID" 2>/dev/null || true
wait "$MONITOR_PID" 2>/dev/null || true

{
  echo "collection_completed_at=$(date --iso-8601=seconds)"
  echo "collector_rc=$COLLECTOR_RC"
  echo "launched_jobs=$(grep -c ' launch ' "$RUN_DIR/meta/events.log" 2>/dev/null || true)"
  echo "completed_jobs=$(grep -c ' finish ' "$RUN_DIR/meta/events.log" 2>/dev/null || true)"
  echo "api_error_logs=$(grep -RIl -E 'insufficient.balance|余额不足|authentication.failed|Missing credentials|rate.limit|429 Too Many Requests' "$RUN_DIR/logs" 2>/dev/null | wc -l || true)"
  echo "state=stopping"
} >> "$STATUS_FILE"

stop_workload
trap - EXIT

{
  echo "stopped_at=$(date --iso-8601=seconds)"
  echo "remaining_minisweagent_containers=$(docker ps --format '{{.Names}}' | grep -c '^minisweagent-' || true)"
  if ((COLLECTOR_RC == 0)); then
    echo "state=complete"
  else
    echo "state=collector_failed"
  fi
} >> "$STATUS_FILE"

cat "$STATUS_FILE"
exit "$COLLECTOR_RC"
