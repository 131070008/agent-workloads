#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SDE64=${SDE64:-/home/higon/sde-external-9.48.0-2024-11-25-lin/sde64}
OUTPUT_ROOT=${SDE_OUTPUT_ROOT:-/home/higon/cunzhe/swe_runs/sde_mix}
STAMP=$(date +%Y%m%d_%H%M%S)
OUTPUT_DIR=${SDE_OUTPUT_DIR:-$OUTPUT_ROOT/sde_mix_$STAMP}

if [[ $# -eq 0 ]]; then
  echo "Usage: $0 COMMAND [ARG ...]" >&2
  exit 2
fi
if [[ ! -x "$SDE64" ]]; then
  echo "SDE executable not found: $SDE64" >&2
  exit 1
fi

mkdir -p "$OUTPUT_DIR"
printf '%q ' "$@" > "$OUTPUT_DIR/command.txt"
printf '\n' >> "$OUTPUT_DIR/command.txt"

"$SDE64" \
  -follow_subprocess \
  -mix \
  -iform 1 \
  -mix_disable_per_function_stats 1 \
  -mix_disable_per_thread_stats 1 \
  -omix "$OUTPUT_DIR/mix.txt" \
  -- "$@" \
  > "$OUTPUT_DIR/stdout.txt" \
  2> "$OUTPUT_DIR/sde.stderr"

python3 "$SCRIPT_DIR/summarize_sde_mix.py" \
  "$OUTPUT_DIR/mix*.txt" \
  --json "$OUTPUT_DIR/summary.json" \
  --markdown "$OUTPUT_DIR/summary.md" \
  > "$OUTPUT_DIR/summary.stdout.txt"

echo "OUTPUT_DIR=$OUTPUT_DIR"
echo "SUMMARY=$OUTPUT_DIR/summary.md"
