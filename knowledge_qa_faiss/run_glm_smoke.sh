#!/usr/bin/env bash
set -euo pipefail

WORKLOAD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$WORKLOAD_DIR/.." && pwd)"

PYTHON_BIN="${PYTHON_BIN:-$REPO_DIR/.venv/bin/python}"
if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="${PYTHON_BIN_FALLBACK:-python3}"
fi

export TOKENIZERS_PARALLELISM="${TOKENIZERS_PARALLELISM:-false}"

if [[ -z "${ZHIPU_API_KEY:-}" ]]; then
  echo "Missing ZHIPU_API_KEY. Export it before running GLM smoke." >&2
  echo "Example: export ZHIPU_API_KEY='<your-bigmodel-key>'" >&2
  exit 2
fi

"$PYTHON_BIN" "$WORKLOAD_DIR/rag_glm_smoke.py" "$@"
