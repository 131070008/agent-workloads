#!/usr/bin/env bash
set -euo pipefail

CUNZHE_ROOT=${CUNZHE_ROOT:-/home/higon/cunzhe}
RUNNER=${RUNNER:-$CUNZHE_ROOT/10_run_aws38_replay_case.sh}
PROBE=${SWE_TIMING_PROBE:-$CUNZHE_ROOT/lifecycle_timing_probe.py}
MANIFEST=${AWS38_MANIFEST:-$CUNZHE_ROOT/swe_runs/aws_public_traces/20250226_sweagent_claude-3-7-sonnet-20250219/aws38_manifest.json}
TIMESTAMP=${TIMESTAMP:-$(date +%Y%m%d_%H%M%S)}
HOST_LABEL=${HOST_LABEL:-$(hostname -s)}
RUN_DIR=${RUN_DIR:-$CUNZHE_ROOT/swe_runs/aws38_timed_full_${HOST_LABEL}_${TIMESTAMP}}
SWE_CPUSET=${SWE_CPUSET:-}
CASE_ROOT=$RUN_DIR/cases

test -x "$RUNNER"
test -f "$PROBE"
test -f "$MANIFEST"
mkdir -p "$CASE_ROOT"

exec 9>"$CUNZHE_ROOT/swe_runs/.aws38_timed_full.lock"
flock -n 9 || { echo "Another AWS-38 timed batch is already running" >&2; exit 1; }

# ReplayModel supplies every action. Do not allow this run to call a cloud LLM.
unset OPENAI_API_KEY ANTHROPIC_API_KEY ZHIPU_API_KEY DEEPSEEK_API_KEY || true

if [[ -n "${CASE_IDS:-}" ]]; then
  read -r -a cases <<< "$CASE_IDS"
else
  mapfile -t cases < <(MANIFEST="$MANIFEST" python3 - <<'PY'
import csv
import json
import os

for case in json.load(open(os.environ["MANIFEST"]))["cases"]:
    print(case["instance_id"])
PY
  )
fi

status_file=$RUN_DIR/status.tsv
summary_file=$RUN_DIR/case_phases.csv
tool_file=$RUN_DIR/tool_calls.csv
category_file=$RUN_DIR/category_summary.csv

if [[ ! -f "$status_file" ]]; then
  printf 'instance_id\tstatus\texit_code\treplay_calls\texpected_calls\telapsed_seconds\tfinished_at\tresult_dir\n' > "$status_file"
fi
printf 'run_dir\t%s\ncase_count\t%s\nhost\t%s\nstarted_at\t%s\n' \
  "$RUN_DIR" "${#cases[@]}" "$HOST_LABEL" "$(date -Is)" > "$RUN_DIR/run_info.tsv"
printf 'swe_cpuset\t%s\n' "${SWE_CPUSET:-unrestricted}" >> "$RUN_DIR/run_info.tsv"

for instance_id in "${cases[@]}"; do
  if awk -F '\t' -v iid="$instance_id" 'NR > 1 && $1 == iid {found=1} END {exit !found}' "$status_file"; then
    echo "===== SKIP completed $instance_id =====" | tee -a "$RUN_DIR/batch.log"
    continue
  fi

  echo "===== START $instance_id $(date -Is) =====" | tee -a "$RUN_DIR/batch.log"
  case_dir=$CASE_ROOT/$instance_id
  mkdir -p "$case_dir"
  start=$(date +%s)
  set +e
  if [[ -n "$SWE_CPUSET" ]]; then
    SWE_TIMING_PROBE="$PROBE" OUTPUT_ROOT="$case_dir" SWE_CPUSET="$SWE_CPUSET" \
      taskset --cpu-list "$SWE_CPUSET" "$RUNNER" "$instance_id" \
      >> "$RUN_DIR/batch.log" 2>&1
  else
    SWE_TIMING_PROBE="$PROBE" OUTPUT_ROOT="$case_dir" \
      "$RUNNER" "$instance_id" >> "$RUN_DIR/batch.log" 2>&1
  fi
  exit_code=$?
  set -e
  elapsed=$(( $(date +%s) - start ))

  result_dir=""
  replay_calls=0
  expected_calls=0
  complete=false
  if [[ -f "$case_dir/LATEST" ]]; then
    result_dir=$(cat "$case_dir/LATEST")
  fi

  if [[ -n "$result_dir" && -f "$result_dir/timing_summary.json" ]]; then
    RESULT_DIR="$result_dir" python3 - <<'PY'
import csv
import json
import os
from pathlib import Path

root = Path(os.environ["RESULT_DIR"])
trajectory = next(root.glob("*.local.traj"))
data = json.loads(trajectory.read_text())
expected = sum(
    item.get("role") == "assistant" and bool(item.get("tool_calls"))
    for item in data["history"]
)
summary_path = root / "timing_summary.json"
summary = json.loads(summary_path.read_text())
summary["expected_replay_calls"] = expected
calls = list(csv.DictReader((root / "tool_calls.csv").open()))
extra = calls[expected:]
summary["autosubmit_calls"] = len(extra)
summary["replay_complete"] = (
    len(calls) >= expected
    and all(call["category"] == "submission" for call in extra)
)
summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
PY
    read -r replay_calls expected_calls complete < <(
      RESULT_DIR="$result_dir" python3 - <<'PY'
import json
import os

d = json.load(open(os.path.join(os.environ["RESULT_DIR"], "timing_summary.json")))
print(d["tool_calls"], d["expected_replay_calls"], str(d["replay_complete"]).lower())
PY
    )
  fi

  if [[ $exit_code -eq 0 && "$complete" == true ]]; then
    status=PASS
  elif [[ $exit_code -eq 0 ]]; then
    status=INCOMPLETE
  else
    status=FAIL
  fi
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$instance_id" "$status" "$exit_code" "$replay_calls" "$expected_calls" \
    "$elapsed" "$(date -Is)" "$result_dir" | tee -a "$status_file"
done

RUN_DIR="$RUN_DIR" python3 - <<'PY'
import csv
import json
import os
from collections import defaultdict
from pathlib import Path

root = Path(os.environ["RUN_DIR"])
statuses = list(csv.DictReader((root / "status.tsv").open(), delimiter="\t"))
phase_rows = []
tool_rows = []
categories = defaultdict(lambda: {"calls": 0, "tool_e2e_ms": 0.0})

for status in statuses:
    result = Path(status["result_dir"])
    summary_path = result / "timing_summary.json"
    if not summary_path.is_file():
        continue
    summary = json.loads(summary_path.read_text())
    phase_rows.append({"instance_id": status["instance_id"], "status": status["status"], **summary})

    calls_path = result / "tool_calls.csv"
    if not calls_path.is_file():
        continue
    for call in csv.DictReader(calls_path.open()):
        row = {"instance_id": status["instance_id"], **call}
        tool_rows.append(row)
        category = call["category"]
        categories[category]["calls"] += 1
        categories[category]["tool_e2e_ms"] += float(call["tool_e2e_ms"])

def write_rows(path, rows):
    if not rows:
        return
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

write_rows(root / "case_phases.csv", phase_rows)
write_rows(root / "tool_calls.csv", tool_rows)

total_tool_ms = sum(item["tool_e2e_ms"] for item in categories.values()) or 1.0
category_rows = []
for name, values in sorted(categories.items(), key=lambda item: -item[1]["tool_e2e_ms"]):
    category_rows.append({
        "category": name,
        "calls": values["calls"],
        "tool_e2e_ms": round(values["tool_e2e_ms"], 3),
        "share_percent": round(values["tool_e2e_ms"] / total_tool_ms * 100.0, 3),
    })
write_rows(root / "category_summary.csv", category_rows)

counts = defaultdict(int)
for row in statuses:
    counts[row["status"]] += 1
with (root / "final_summary.txt").open("w") as handle:
    handle.write(f"cases={len(statuses)}\n")
    for status in ("PASS", "INCOMPLETE", "FAIL"):
        handle.write(f"{status.lower()}={counts[status]}\n")
    handle.write(f"total_elapsed_seconds={sum(int(row['elapsed_seconds']) for row in statuses)}\n")
PY

printf 'finished_at\t%s\n' "$(date -Is)" >> "$RUN_DIR/run_info.tsv"
cat "$RUN_DIR/final_summary.txt" | tee -a "$RUN_DIR/batch.log"
echo "COMPLETE run_dir=$RUN_DIR" | tee -a "$RUN_DIR/batch.log"
