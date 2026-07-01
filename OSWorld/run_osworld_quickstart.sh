#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OSW_DIR="$ROOT_DIR/workloads/OSWorld/upstream/OSWorld"

cd "$OSW_DIR"

PROVIDER_ARGS=()
if [[ -n "${OSW_PROVIDER:-}" ]]; then
  PROVIDER_ARGS+=(--provider_name "$OSW_PROVIDER")
fi
if [[ -n "${OSW_VM_PATH:-}" ]]; then
  PROVIDER_ARGS+=(--path_to_vm "$OSW_VM_PATH")
fi

python quickstart.py "${PROVIDER_ARGS[@]}"
