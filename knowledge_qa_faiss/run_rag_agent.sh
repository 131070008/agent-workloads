#!/usr/bin/env bash
set -euo pipefail

WORKLOAD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$WORKLOAD_DIR/.." && pwd)"
WORK_DIR="${WORK_DIR:-$REPO_DIR}"
CPU_CENTRIC_ROOT="${CPU_CENTRIC_ROOT:-$REPO_DIR/../cpu-centric-agentic-ai}"

PYTHON_BIN="${PYTHON_BIN:-$REPO_DIR/.venv/bin/python}"
if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="${PYTHON_BIN_FALLBACK:-python3}"
fi
HARNESS="${HARNESS:-$CPU_CENTRIC_ROOT/haystack/retrieval.py}"
STORE_DIR="${STORE_DIR:-$WORKLOAD_DIR/datasets/beir_scifact_smoke/prebuilt_store}"
QUERY_FILE="${QUERY_FILE:-$WORKLOAD_DIR/datasets/beir_scifact_smoke/queries/evidence_5.txt}"
MODEL="${MODEL:-sentence-transformers/all-MiniLM-L6-v2}"

LLM_API_URL="${LLM_API_URL:-http://127.0.0.1:11434/v1}"
LLM_MODEL="${LLM_MODEL:-qwen3.6:27b}"
LLM_API_KEY="${LLM_API_KEY:-EMPTY}"
LLM_MAX_TOKENS="${LLM_MAX_TOKENS:-128}"
LLM_TEMPERATURE="${LLM_TEMPERATURE:-0.2}"
LLM_PROVIDER="${LLM_PROVIDER:-ollama}"
LLM_NUM_CTX="${LLM_NUM_CTX:-4096}"

TOP_K="${TOP_K:-5}"
OMP_THREADS="${OMP_THREADS:-4}"
EMBED_BATCH="${EMBED_BATCH:-8}"
BACKEND="${BACKEND:-torch}"
RAG_WORKERS="${RAG_WORKERS:-1}"

export HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}"
export TRANSFORMERS_OFFLINE="${TRANSFORMERS_OFFLINE:-1}"
export TOKENIZERS_PARALLELISM="${TOKENIZERS_PARALLELISM:-false}"

cd "$WORK_DIR"

"$PYTHON_BIN" "$HARNESS" batch-query-rag \
  --store-dir "$STORE_DIR" \
  --model "$MODEL" \
  --backend "$BACKEND" \
  --top-k "$TOP_K" \
  --omp-threads "$OMP_THREADS" \
  --embed-batch "$EMBED_BATCH" \
  --query-file "$QUERY_FILE" \
  --rag-workers "$RAG_WORKERS" \
  --llm-api-url "$LLM_API_URL" \
  --llm-model "$LLM_MODEL" \
  --llm-api-key "$LLM_API_KEY" \
  --llm-max-tokens "$LLM_MAX_TOKENS" \
  --llm-temperature "$LLM_TEMPERATURE" \
  --llm-provider "$LLM_PROVIDER" \
  --llm-num-ctx "$LLM_NUM_CTX" \
  "$@"
