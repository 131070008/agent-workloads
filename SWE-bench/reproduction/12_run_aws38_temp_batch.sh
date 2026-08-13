#!/usr/bin/env bash
set -euo pipefail

CUNZHE_ROOT=${CUNZHE_ROOT:-/home/higon/cunzhe}
RUNNER=${RUNNER:-$CUNZHE_ROOT/10_run_aws38_replay_case.sh}
MANIFEST=${AWS38_MANIFEST:-$CUNZHE_ROOT/swe_runs/aws_public_traces/20250226_sweagent_claude-3-7-sonnet-20250219/aws38_manifest.json}
TIMESTAMP=${TIMESTAMP:-$(date +%Y%m%d_%H%M%S)}
HOST_LABEL=${HOST_LABEL:-$(hostname -s)}
RUN_DIR=${RUN_DIR:-$CUNZHE_ROOT/swe_runs/tmp_aws38_${HOST_LABEL}_${TIMESTAMP}}
CASE_OUTPUT_ROOT="$RUN_DIR/cases"

test -x "$RUNNER"
test -f "$MANIFEST"
mkdir -p "$CASE_OUTPUT_ROOT"

exec 9>"$CUNZHE_ROOT/swe_runs/.aws38_temp_batch.lock"
flock -n 9 || { echo "Another AWS-38 batch is already running" >&2; exit 1; }

# ReplayModel supplies recorded actions. Explicitly remove cloud credentials so
# this temporary validation cannot call an LLM API.
unset OPENAI_API_KEY ANTHROPIC_API_KEY ZHIPU_API_KEY DEEPSEEK_API_KEY || true

mapfile -t cases < <(MANIFEST="$MANIFEST" python3 - <<'PY'
import json
import os
for case in json.load(open(os.environ["MANIFEST"]))["cases"]:
    print(case["instance_id"])
PY
)

printf 'instance_id\tstatus\telapsed_seconds\tfinished_at\n' > "$RUN_DIR/status.tsv"
printf 'run_dir\t%s\ncase_count\t%s\nstarted_at\t%s\n' \
  "$RUN_DIR" "${#cases[@]}" "$(date -Is)" > "$RUN_DIR/run_info.tsv"

for instance_id in "${cases[@]}"; do
  echo "===== $instance_id =====" | tee -a "$RUN_DIR/batch.log"
  start=$(date +%s)
  if OUTPUT_ROOT="$CASE_OUTPUT_ROOT" "$RUNNER" "$instance_id" >> "$RUN_DIR/batch.log" 2>&1; then
    status=PASS
  else
    status=FAIL
  fi
  elapsed=$(( $(date +%s) - start ))
  printf '%s\t%s\t%s\t%s\n' "$instance_id" "$status" "$elapsed" "$(date -Is)" \
    | tee -a "$RUN_DIR/status.tsv"
done

printf 'finished_at\t%s\n' "$(date -Is)" >> "$RUN_DIR/run_info.tsv"
pass_count=$(awk -F '\t' '$2 == "PASS" {count++} END {print count+0}' "$RUN_DIR/status.tsv")
fail_count=$(awk -F '\t' '$2 == "FAIL" {count++} END {print count+0}' "$RUN_DIR/status.tsv")
printf 'pass_count\t%s\nfail_count\t%s\n' "$pass_count" "$fail_count" >> "$RUN_DIR/run_info.tsv"
echo "COMPLETE pass=$pass_count fail=$fail_count run_dir=$RUN_DIR" | tee -a "$RUN_DIR/batch.log"
