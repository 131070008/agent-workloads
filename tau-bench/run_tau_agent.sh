#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
UPSTREAM_DIR="${UPSTREAM_DIR:-$ROOT_DIR/workloads/tau-bench/upstream/tau-bench-src}"
PYTHON_BIN="${PYTHON_BIN:-$ROOT_DIR/.venv-tau/bin/python}"

ENV_NAME="${ENV_NAME:-airline}"
AGENT_STRATEGY="${AGENT_STRATEGY:-tool-calling}"
USER_STRATEGY="${USER_STRATEGY:-llm}"
MODEL="${MODEL:-qwen3:8b}"
MODEL_PROVIDER="${MODEL_PROVIDER:-ollama}"
USER_MODEL="${USER_MODEL:-$MODEL}"
USER_MODEL_PROVIDER="${USER_MODEL_PROVIDER:-$MODEL_PROVIDER}"
MAX_CONCURRENCY="${MAX_CONCURRENCY:-1}"
TASK_IDS="${TASK_IDS:-0}"
NUM_TRIALS="${NUM_TRIALS:-1}"
LOG_DIR="${LOG_DIR:-$ROOT_DIR/workloads/tau-bench/results}"
OLLAMA_API_BASE="${OLLAMA_API_BASE:-http://127.0.0.1:11434}"
TAU_MAX_STEPS="${TAU_MAX_STEPS:-8}"
TAU_LLM_TIMEOUT="${TAU_LLM_TIMEOUT:-180}"
TAU_LLM_NUM_CTX="${TAU_LLM_NUM_CTX:-4096}"
TAU_LLM_THINK="${TAU_LLM_THINK:-false}"

if [[ ! -f "$UPSTREAM_DIR/run.py" ]]; then
  cat >&2 <<EOF
tau-bench upstream runner is not installed:
  $UPSTREAM_DIR/run.py

This script is the real agent-bench entry point, but it needs the official
tau-bench source tree first. Clone it into:
  $UPSTREAM_DIR

Then set provider credentials or a compatible local adapter and rerun.
EOF
  exit 2
fi

if [[ ! -x "$PYTHON_BIN" ]]; then
  cat >&2 <<EOF
Python environment is not installed:
  $PYTHON_BIN

Create it and install tau-bench dependencies first:
  python -m venv $ROOT_DIR/.venv-tau
  $ROOT_DIR/.venv-tau/bin/python -m pip install -e $UPSTREAM_DIR
EOF
  exit 2
fi

mkdir -p "$LOG_DIR"
export OLLAMA_API_BASE
export PYTHONUNBUFFERED=1
export LITELLM_LOG="${LITELLM_LOG:-ERROR}"
export TAU_MAX_STEPS
export TAU_LLM_TIMEOUT
export TAU_LLM_NUM_CTX
export TAU_LLM_THINK

cd "$UPSTREAM_DIR"

"$PYTHON_BIN" -u run.py \
  --num-trials "$NUM_TRIALS" \
  --agent-strategy "$AGENT_STRATEGY" \
  --env "$ENV_NAME" \
  --model "$MODEL" \
  --model-provider "$MODEL_PROVIDER" \
  --user-model "$USER_MODEL" \
  --user-model-provider "$USER_MODEL_PROVIDER" \
  --user-strategy "$USER_STRATEGY" \
  --max-concurrency "$MAX_CONCURRENCY" \
  --task-ids "$TASK_IDS" \
  --log-dir "$LOG_DIR" \
  "$@"
