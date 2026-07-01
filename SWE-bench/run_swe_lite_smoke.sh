#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-$ROOT_DIR/cpu-centric-agentic-ai/.venv-swe/bin/python}"

"$PYTHON_BIN" "$ROOT_DIR/workloads/SWE-bench/swe_lite_harness.py" "$@"
