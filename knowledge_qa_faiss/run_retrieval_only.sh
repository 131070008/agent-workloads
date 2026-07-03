#!/usr/bin/env bash
set -euo pipefail

WORKLOAD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$WORKLOAD_DIR/.." && pwd)"
WORK_DIR="${WORK_DIR:-$REPO_DIR}"

PYTHON_BIN="${PYTHON_BIN:-$REPO_DIR/.venv/bin/python}"
if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="${PYTHON_BIN_FALLBACK:-python3}"
fi
HARNESS="${HARNESS:-$WORKLOAD_DIR/retrieval_only.py}"
STORE_DIR="${STORE_DIR:-$WORKLOAD_DIR/datasets/beir_scifact_smoke/prebuilt_store}"
QUERY_FILE="${QUERY_FILE:-$WORKLOAD_DIR/datasets/beir_scifact_smoke/queries/evidence_5.txt}"
LOCAL_EMBED_MODEL_DIR="${LOCAL_EMBED_MODEL_DIR:-$HOME/cunzhe/models/all-MiniLM-L6-v2}"
DEFAULT_MODEL="sentence-transformers/all-MiniLM-L6-v2"
if [[ -d "$LOCAL_EMBED_MODEL_DIR" ]]; then
  DEFAULT_MODEL="$LOCAL_EMBED_MODEL_DIR"
fi
MODEL="${MODEL:-$DEFAULT_MODEL}"

TOP_K="${TOP_K:-5}"
OMP_THREADS="${OMP_THREADS:-4}"
EMBED_BATCH="${EMBED_BATCH:-8}"
BACKEND="${BACKEND:-torch}"

export HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}"
export TRANSFORMERS_OFFLINE="${TRANSFORMERS_OFFLINE:-1}"
export TOKENIZERS_PARALLELISM="${TOKENIZERS_PARALLELISM:-false}"

cd "$WORK_DIR"

"$PYTHON_BIN" "$HARNESS" \
  --store-dir "$STORE_DIR" \
  --model "$MODEL" \
  --backend "$BACKEND" \
  --top-k "$TOP_K" \
  --omp-threads "$OMP_THREADS" \
  --embed-batch "$EMBED_BATCH" \
  --query-file "$QUERY_FILE"
