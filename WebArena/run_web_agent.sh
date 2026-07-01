#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
UPSTREAM_DIR="${UPSTREAM_DIR:-$ROOT_DIR/workloads/WebArena/upstream/webarena-src}"
PYTHON_BIN="${PYTHON_BIN:-$ROOT_DIR/.venv-webarena310/bin/python}"
MODE="${MODE:-llm}"
CONFIG="${CONFIG:-config_files/examples/2.json}"
MODEL="${MODEL:-qwen3:8b}"
MAX_STEPS="${MAX_STEPS:-2}"
MAX_TOKENS="${MAX_TOKENS:-512}"
OPENAI_API_BASE="${OPENAI_API_BASE:-http://127.0.0.1:11434/v1}"
OPENAI_API_KEY="${OPENAI_API_KEY:-EMPTY}"

if [[ ! -d "$UPSTREAM_DIR" ]]; then
  cat >&2 <<EOF
WebArena runner is not installed:
  $UPSTREAM_DIR

This is the planned web-agent bench entry point. Install a WebArena-compatible
runner here, then wire this script to the selected smoke task and LLM endpoint.
EOF
  exit 2
fi

if [[ ! -x "$PYTHON_BIN" ]]; then
  cat >&2 <<EOF
WebArena Python environment is not installed:
  $PYTHON_BIN

Expected setup:
  /opt/homebrew/bin/python3.10 -m venv .venv-webarena310
  .venv-webarena310/bin/python -m pip install \\
    -r workloads/WebArena/requirements-local.txt \\
    -e workloads/WebArena/upstream/webarena-src
  .venv-webarena310/bin/python -m playwright install chromium
EOF
  exit 2
fi

cd "$ROOT_DIR"
OPENAI_API_BASE="$OPENAI_API_BASE" \
OPENAI_API_KEY="$OPENAI_API_KEY" \
"$PYTHON_BIN" workloads/WebArena/run_webarena_example.py \
  --mode "$MODE" \
  --config "$CONFIG" \
  --model "$MODEL" \
  --max-steps "$MAX_STEPS" \
  --max-tokens "$MAX_TOKENS"
