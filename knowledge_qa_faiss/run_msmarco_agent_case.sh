#!/usr/bin/env bash
set -euo pipefail

WORKLOAD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$WORKLOAD_DIR/.." && pwd)"

PYTHON_BIN="${PYTHON_BIN:-$REPO_DIR/.venv/bin/python}"
if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="${PYTHON_BIN_FALLBACK:-python3}"
fi

DEFAULT_QUERY="what is paula deen's brother"
export QUERY="${QUERY:-$DEFAULT_QUERY}"
export TOP_K="${TOP_K:-5}"
export RETRIEVER_URL="${RETRIEVER_URL:-http://127.0.0.1:18080}"
export LLM_MODEL="${LLM_MODEL:-glm-4.5-air}"
export LLM_MAX_TOKENS="${LLM_MAX_TOKENS:-512}"
export LLM_TEMPERATURE="${LLM_TEMPERATURE:-0.2}"
export HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}"
export TRANSFORMERS_OFFLINE="${TRANSFORMERS_OFFLINE:-1}"
export TOKENIZERS_PARALLELISM="${TOKENIZERS_PARALLELISM:-false}"

cmd=("$PYTHON_BIN" "$WORKLOAD_DIR/rag_agent_case.py" "$@")

if [[ -n "${AGENT_CORE:-}" ]] && command -v taskset >/dev/null 2>&1; then
  exec taskset -c "$AGENT_CORE" "${cmd[@]}"
fi

exec "${cmd[@]}"
