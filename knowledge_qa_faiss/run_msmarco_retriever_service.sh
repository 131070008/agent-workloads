#!/usr/bin/env bash
set -euo pipefail

WORKLOAD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$WORKLOAD_DIR/.." && pwd)"

PYTHON_BIN="${PYTHON_BIN:-$REPO_DIR/.venv/bin/python}"
if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="${PYTHON_BIN_FALLBACK:-python3}"
fi

LOCAL_EMBED_MODEL_DIR="${LOCAL_EMBED_MODEL_DIR:-$HOME/cunzhe/models/all-MiniLM-L6-v2}"
DEFAULT_MODEL="sentence-transformers/all-MiniLM-L6-v2"
if [[ -d "$LOCAL_EMBED_MODEL_DIR" ]]; then
  DEFAULT_MODEL="$LOCAL_EMBED_MODEL_DIR"
fi

export STORE_DIR="${STORE_DIR:-$HOME/cunzhe/datasets/msmarco/faiss_hnsw_m48_efc500_store}"
export INDEX_FILE_NAME="${INDEX_FILE_NAME:-hnsw.index}"
export HNSW_EF_SEARCH="${HNSW_EF_SEARCH:-200}"
export MODEL="${MODEL:-$DEFAULT_MODEL}"
export TOP_K="${TOP_K:-5}"
export RETRIEVER_HOST="${RETRIEVER_HOST:-127.0.0.1}"
export RETRIEVER_PORT="${RETRIEVER_PORT:-18080}"

export HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}"
export TRANSFORMERS_OFFLINE="${TRANSFORMERS_OFFLINE:-1}"
export TOKENIZERS_PARALLELISM="${TOKENIZERS_PARALLELISM:-false}"
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-1}"
export MKL_NUM_THREADS="${MKL_NUM_THREADS:-1}"
export OPENBLAS_NUM_THREADS="${OPENBLAS_NUM_THREADS:-1}"
export NUMEXPR_NUM_THREADS="${NUMEXPR_NUM_THREADS:-1}"
export MALLOC_ARENA_MAX="${MALLOC_ARENA_MAX:-2}"

cmd=("$PYTHON_BIN" "$WORKLOAD_DIR/rag_retriever_service.py" "$@")

if [[ -n "${RETRIEVER_CORE:-}" ]] && command -v taskset >/dev/null 2>&1; then
  exec taskset -c "$RETRIEVER_CORE" "${cmd[@]}"
fi

exec "${cmd[@]}"
