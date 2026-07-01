#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OSW_DIR="$ROOT_DIR/workloads/OSWorld/upstream/OSWorld"

cd "$OSW_DIR"

OSW_PROVIDER="${OSW_PROVIDER:-vmware}"
OSW_MODEL="${OSW_MODEL:-gpt-4o}"
OSW_OBSERVATION="${OSW_OBSERVATION:-screenshot}"
OSW_MAX_STEPS="${OSW_MAX_STEPS:-15}"
OSW_SLEEP_AFTER_EXECUTION="${OSW_SLEEP_AFTER_EXECUTION:-3}"
OSW_RESULT_DIR="${OSW_RESULT_DIR:-$ROOT_DIR/workloads/OSWorld/results}"
OSW_TEST_META="${OSW_TEST_META:-evaluation_examples/test_small.json}"
OSW_CLIENT_PASSWORD="${OSW_CLIENT_PASSWORD:-password}"

mkdir -p "$OSW_RESULT_DIR"

ARGS=(
  --provider_name "$OSW_PROVIDER"
  --headless
  --observation_type "$OSW_OBSERVATION"
  --model "$OSW_MODEL"
  --sleep_after_execution "$OSW_SLEEP_AFTER_EXECUTION"
  --max_steps "$OSW_MAX_STEPS"
  --result_dir "$OSW_RESULT_DIR"
  --test_all_meta_path "$OSW_TEST_META"
  --client_password "$OSW_CLIENT_PASSWORD"
)

if [[ -n "${OSW_VM_PATH:-}" ]]; then
  ARGS+=(--path_to_vm "$OSW_VM_PATH")
fi

python run.py "${ARGS[@]}"
