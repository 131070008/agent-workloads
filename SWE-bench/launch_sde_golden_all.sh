#!/usr/bin/env bash
set -euo pipefail

ROOT=/home/higon/cunzhe/agent-workloads
PYTHON=$ROOT/.venv-swe/bin/python
SDE_HOME=/home/higon/sde-external-9.48.0-2024-11-25-lin
RUN_ROOT=/home/higon/cunzhe/swe_runs
STAMP=$(date +%Y%m%d_%H%M%S)
OUTPUT_DIR=${1:-$RUN_ROOT/sde_golden_all_$STAMP}
LATEST_FILE=$RUN_ROOT/sde_golden_latest.txt

mkdir -p "$OUTPUT_DIR"
if [[ -f "$OUTPUT_DIR/runner.pid" ]]; then
  OLD_PID=$(cat "$OUTPUT_DIR/runner.pid")
  if kill -0 "$OLD_PID" 2>/dev/null; then
    echo "SDE Golden run is already active: pid=$OLD_PID output=$OUTPUT_DIR" >&2
    exit 1
  fi
fi

umask 027
nohup "$PYTHON" "$ROOT/SWE-bench/run_sde_golden_set.py" \
  --golden flash=/home/higon/cunzhe/swe_runs/golden_replay/flash \
  --golden pro=/home/higon/cunzhe/swe_runs/golden_replay/pro \
  --output-dir "$OUTPUT_DIR" \
  --repo "$ROOT" \
  --sde-home "$SDE_HOME" \
  --cpus 0-7 \
  --workers 8 \
  --action-timeout 1800 \
  --case-timeout 21600 \
  --container-memory 16g \
  --container-pids-limit 4096 \
  --resume \
  > "$OUTPUT_DIR/runner.log" 2>&1 < /dev/null &
PID=$!

printf '%s\n' "$PID" > "$OUTPUT_DIR/runner.pid"
printf '%s\n' "$OUTPUT_DIR" > "$LATEST_FILE"
cat > "$OUTPUT_DIR/launch_metadata.txt" <<EOF
started_at=$(date -Iseconds)
pid=$PID
output_dir=$OUTPUT_DIR
golden=flash+pro
cases=60
cpus=0-7
workers=8
network=none
analysis_privileges=pid-host,SYS_ADMIN,SYS_PTRACE,seccomp-unconfined
EOF

echo "PID=$PID"
echo "OUTPUT_DIR=$OUTPUT_DIR"
echo "LOG=$OUTPUT_DIR/runner.log"
