#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SDE_HOME=${SDE_HOME:-/home/higon/sde-external-9.48.0-2024-11-25-lin}
SDE64="$SDE_HOME/sde64"
IMAGE=${SDE_SWE_IMAGE:-}
CPUSET=${SDE_CPUSET:-0}
OUTPUT_ROOT=${SDE_OUTPUT_ROOT:-/home/higon/cunzhe/swe_runs/sde_swe_toolcalls}
STAMP=$(date +%Y%m%d_%H%M%S)
OUTPUT_DIR=${SDE_OUTPUT_DIR:-$OUTPUT_ROOT/sde_swe_toolcall_$STAMP}

if [[ -z "$IMAGE" || $# -ne 1 ]]; then
  echo "Usage: SDE_SWE_IMAGE=IMAGE $0 'SHELL COMMAND'" >&2
  exit 2
fi
if [[ ! -x "$SDE64" ]]; then
  echo "SDE executable not found: $SDE64" >&2
  exit 1
fi

COMMAND=$1
mkdir -p "$OUTPUT_DIR"
printf '%s\n' "$IMAGE" > "$OUTPUT_DIR/image.txt"
printf '%s\n' "$COMMAND" > "$OUTPUT_DIR/command.txt"

cat > "$OUTPUT_DIR/metadata.txt" <<EOF
timestamp=$STAMP
hostname=$(hostname)
kernel=$(uname -r)
image=$IMAGE
cpuset=$CPUSET
network=none
sde64=$SDE64
scope=single Sandbox ToolCall
analysis_privileges=pid-host,SYS_ADMIN,SYS_PTRACE,seccomp-unconfined
EOF

set +e
docker run --rm \
  --cpuset-cpus="$CPUSET" \
  --network none \
  --pid host \
  --cap-add SYS_ADMIN \
  --cap-add SYS_PTRACE \
  --security-opt seccomp=unconfined \
  --memory 16g \
  --pids-limit 4096 \
  -w /testbed \
  -e SDE_TOOL_COMMAND="$COMMAND" \
  -v "$SDE_HOME:/opt/intel-sde:ro" \
  -v "$OUTPUT_DIR:/sde-output" \
  "$IMAGE" \
  /opt/intel-sde/sde64 \
    -follow_subprocess \
    -mix \
    -iform 1 \
    -mix_disable_per_function_stats 1 \
    -mix_disable_per_thread_stats 1 \
    -omix /sde-output/mix.txt \
    -- bash -lc 'exec bash -lc "$SDE_TOOL_COMMAND"' \
  > "$OUTPUT_DIR/stdout.txt" \
  2> "$OUTPUT_DIR/sde.stderr"
COMMAND_RC=$?
set -e

printf '%s\n' "$COMMAND_RC" > "$OUTPUT_DIR/command_returncode.txt"

python3 "$SCRIPT_DIR/summarize_sde_mix.py" \
  "$OUTPUT_DIR/mix*.txt" \
  --json "$OUTPUT_DIR/summary.json" \
  --markdown "$OUTPUT_DIR/summary.md" \
  > "$OUTPUT_DIR/summary.stdout.txt"

echo "COMMAND_RC=$COMMAND_RC"
echo "OUTPUT_DIR=$OUTPUT_DIR"
echo "SUMMARY=$OUTPUT_DIR/summary.md"
