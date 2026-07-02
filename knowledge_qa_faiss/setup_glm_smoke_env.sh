#!/usr/bin/env bash
set -euo pipefail

WORKLOAD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$WORKLOAD_DIR/.." && pwd)"
VENV_DIR="${VENV_DIR:-$REPO_DIR/.venv}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
PIP_INDEX_URL="${PIP_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple}"

"$PYTHON_BIN" -m venv "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/python" -m pip install \
  --index-url "$PIP_INDEX_URL" \
  -r "$WORKLOAD_DIR/requirements-glm-smoke.txt"

cat <<MSG
GLM smoke environment is ready:
  $VENV_DIR/bin/python

Run:
  export ZHIPU_API_KEY='<your-bigmodel-key>'
  $WORKLOAD_DIR/run_glm_smoke.sh
MSG
