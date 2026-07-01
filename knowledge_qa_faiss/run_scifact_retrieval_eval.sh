#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK_DIR="${WORK_DIR:-$ROOT_DIR}"

PYTHON_BIN="${PYTHON_BIN:-/Users/cztian/workspace/myself/agent/cpu-centric-agentic-ai/.venv/bin/python}"
HARNESS="${HARNESS:-$ROOT_DIR/workloads/knowledge_qa_faiss/evaluate_scifact_retrieval.py}"
OUTPUT_JSON="${OUTPUT_JSON:-$ROOT_DIR/workloads/knowledge_qa_faiss/results/scifact_retrieval_eval.json}"

export HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}"
export TRANSFORMERS_OFFLINE="${TRANSFORMERS_OFFLINE:-1}"
export TOKENIZERS_PARALLELISM="${TOKENIZERS_PARALLELISM:-false}"

cd "$WORK_DIR"

"$PYTHON_BIN" "$HARNESS" \
  --output-json "$OUTPUT_JSON" \
  "$@"
