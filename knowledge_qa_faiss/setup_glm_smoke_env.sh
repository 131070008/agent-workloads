#!/usr/bin/env bash
set -euo pipefail

WORKLOAD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$WORKLOAD_DIR/.." && pwd)"
VENV_DIR="${VENV_DIR:-$REPO_DIR/.venv}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
PIP_INDEX_URL="${PIP_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple}"

if ! "$PYTHON_BIN" -m venv "$VENV_DIR"; then
  echo "python3 -m venv failed; falling back to user-level virtualenv." >&2
  "$PYTHON_BIN" -m pip install --user --index-url "$PIP_INDEX_URL" virtualenv
  "$PYTHON_BIN" -m virtualenv --clear "$VENV_DIR"
fi
"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/python" -m pip install \
  --index-url "$PIP_INDEX_URL" \
  -r "$WORKLOAD_DIR/requirements-glm-smoke.txt"

cat <<MSG
GLM smoke environment is ready:
  $VENV_DIR/bin/python

Run:
  $WORKLOAD_DIR/run_glm_smoke.sh --retrieval-only
  export ZHIPU_API_KEY='<your-bigmodel-key>'
  $WORKLOAD_DIR/run_glm_smoke.sh
MSG
