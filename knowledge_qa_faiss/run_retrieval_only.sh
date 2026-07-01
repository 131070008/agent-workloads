#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK_DIR="${WORK_DIR:-$ROOT_DIR}"

PYTHON_BIN="${PYTHON_BIN:-/Users/cztian/workspace/myself/agent/cpu-centric-agentic-ai/.venv/bin/python}"
HARNESS="${HARNESS:-$ROOT_DIR/workloads/knowledge_qa_faiss/retrieval_only.py}"
STORE_DIR="${STORE_DIR:-$ROOT_DIR/workloads/knowledge_qa_faiss/datasets/beir_scifact_smoke/prebuilt_store}"
QUERY_FILE="${QUERY_FILE:-$ROOT_DIR/workloads/knowledge_qa_faiss/datasets/beir_scifact_smoke/queries/evidence_5.txt}"
MODEL="${MODEL:-/Users/cztian/.cache/huggingface/hub/models--sentence-transformers--all-MiniLM-L6-v2/snapshots/1110a243fdf4706b3f48f1d95db1a4f5529b4d41}"

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
