#!/usr/bin/env bash
set -euo pipefail

WORKLOAD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$WORKLOAD_DIR/.." && pwd)"

PYTHON_BIN="${PYTHON_BIN:-$REPO_DIR/.venv/bin/python}"
if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="${PYTHON_BIN_FALLBACK:-python3}"
fi

export TOKENIZERS_PARALLELISM="${TOKENIZERS_PARALLELISM:-false}"

needs_api_key=1
has_query_embeddings=0
has_query_file=0
for arg in "$@"; do
  case "$arg" in
    --retrieval-only|--llm-api-key|--llm-api-key=*)
      needs_api_key=0
      ;;
    --query-embeddings-npy|--query-embeddings-npy=*)
      has_query_embeddings=1
      ;;
    --query-file|--query-file=*)
      has_query_file=1
      ;;
  esac
done

if [[ "$needs_api_key" -eq 1 && -z "${ZHIPU_API_KEY:-}" ]]; then
  echo "Missing ZHIPU_API_KEY. Export it before running GLM smoke." >&2
  echo "Example: export ZHIPU_API_KEY='<your-bigmodel-key>'" >&2
  exit 2
fi

default_query_embeddings="$WORKLOAD_DIR/datasets/beir_scifact_smoke/queries/evidence_5.all-MiniLM-L6-v2.npy"
extra_args=()
if [[ "$has_query_embeddings" -eq 0 && "$has_query_file" -eq 0 && -f "$default_query_embeddings" ]]; then
  extra_args=(--query-embeddings-npy "$default_query_embeddings")
fi

"$PYTHON_BIN" "$WORKLOAD_DIR/rag_glm_smoke.py" "${extra_args[@]}" "$@"
