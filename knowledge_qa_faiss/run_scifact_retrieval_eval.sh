#!/usr/bin/env bash
set -euo pipefail

WORKLOAD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$WORKLOAD_DIR/.." && pwd)"
WORK_DIR="${WORK_DIR:-$REPO_DIR}"

PYTHON_BIN="${PYTHON_BIN:-$REPO_DIR/.venv/bin/python}"
if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="${PYTHON_BIN_FALLBACK:-python3}"
fi
HARNESS="${HARNESS:-$WORKLOAD_DIR/evaluate_scifact_retrieval.py}"
OUTPUT_JSON="${OUTPUT_JSON:-$WORKLOAD_DIR/results/scifact_retrieval_eval.json}"
MODEL="${MODEL:-sentence-transformers/all-MiniLM-L6-v2}"

export HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}"
export TRANSFORMERS_OFFLINE="${TRANSFORMERS_OFFLINE:-1}"
export TOKENIZERS_PARALLELISM="${TOKENIZERS_PARALLELISM:-false}"

mkdir -p "$(dirname "$OUTPUT_JSON")"
cd "$WORK_DIR"

"$PYTHON_BIN" "$HARNESS" \
  --model "$MODEL" \
  --output-json "$OUTPUT_JSON" \
  "$@"
