#!/usr/bin/env bash
set -euo pipefail

RUN_ROOT=/home/higon/cunzhe/swe_runs
LATEST_FILE=$RUN_ROOT/sde_golden_latest.txt
OUTPUT_DIR=${1:-}
if [[ -z "$OUTPUT_DIR" ]]; then
  if [[ ! -f "$LATEST_FILE" ]]; then
    echo "No SDE Golden run has been launched." >&2
    exit 1
  fi
  OUTPUT_DIR=$(cat "$LATEST_FILE")
fi

echo "OUTPUT_DIR=$OUTPUT_DIR"
if [[ -f "$OUTPUT_DIR/runner.pid" ]]; then
  PID=$(cat "$OUTPUT_DIR/runner.pid")
  if kill -0 "$PID" 2>/dev/null; then
    echo "STATE=running"
  else
    echo "STATE=stopped"
  fi
  echo "PID=$PID"
fi

python3 - "$OUTPUT_DIR" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
status_path = root / "run_status.json"
if status_path.exists():
    data = json.loads(status_path.read_text())
    print("STATES=" + json.dumps(data.get("states", {}), ensure_ascii=False, sort_keys=True))
    print(f"RECORDED_CASES={len(data.get('results', []))}")
config_path = root / "run_config.json"
if config_path.exists():
    config = json.loads(config_path.read_text())
    print(f"EXPECTED_CASES={config.get('job_count')}")
    print(f"EXPECTED_ACTIONS={config.get('expected_action_count')}")
summary_path = root / "sde_golden_summary.md"
if summary_path.exists():
    print(f"SUMMARY={summary_path}")
PY

printf 'ACTIVE_CONTAINERS='
docker ps --filter name=minisweagent --format '{{.ID}}' | wc -l
echo "LOG=$OUTPUT_DIR/runner.log"
tail -n 15 "$OUTPUT_DIR/runner.log" 2>/dev/null || true
