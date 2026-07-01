#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

HARBOR_BIN="${HARBOR_BIN:-/Users/cztian/.local/bin/harbor}"
TB_DATASET_DIR="${TB_DATASET_DIR:-workloads/Terminal-Bench/upstream/terminal-bench-2}"
TB_TASK="${TB_TASK:-fix-git}"
TB_MODEL="${TB_MODEL:-qwen3:8b}"
TB_MAX_TURNS="${TB_MAX_TURNS:-15}"
TB_MAX_TOKENS="${TB_MAX_TOKENS:-2048}"
TB_CONTEXT_TOKENS="${TB_CONTEXT_TOKENS:-32768}"
OLLAMA_API_BASE="${OLLAMA_API_BASE:-http://127.0.0.1:11434}"

export OLLAMA_API_BASE
export HTTP_PROXY="${HTTP_PROXY:-http://127.0.0.1:7897}"
export HTTPS_PROXY="${HTTPS_PROXY:-http://127.0.0.1:7897}"

"$HARBOR_BIN" run \
  -p "$TB_DATASET_DIR/$TB_TASK" \
  -a terminus-2 \
  -m "ollama/$TB_MODEL" \
  -n 1 \
  -o workloads/Terminal-Bench/results \
  --yes \
  --ak "max_turns=$TB_MAX_TURNS" \
  --ak record_terminal_session=false \
  --ak enable_summarize=false \
  --ak proactive_summarization_threshold=0 \
  --ak temperature=0 \
  --ak "llm_call_kwargs={\"max_tokens\":$TB_MAX_TOKENS}" \
  --ak "model_info={\"max_input_tokens\":$TB_CONTEXT_TOKENS,\"max_output_tokens\":$TB_MAX_TOKENS,\"input_cost_per_token\":0,\"output_cost_per_token\":0}" \
  --ae "OLLAMA_API_BASE=$OLLAMA_API_BASE" \
  --ve "HTTP_PROXY=${TB_VERIFIER_HTTP_PROXY:-http://192.168.5.2:7897}" \
  --ve "HTTPS_PROXY=${TB_VERIFIER_HTTPS_PROXY:-http://192.168.5.2:7897}"
