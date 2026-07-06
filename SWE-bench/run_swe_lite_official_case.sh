#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-$ROOT_DIR/.venv-swe/bin/python}"
if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="${PYTHON_BIN_FALLBACK:-python3}"
fi

if [[ -z "${OPENAI_API_KEY:-}" && -n "${ZHIPU_API_KEY:-}" ]]; then
  export OPENAI_API_KEY="$ZHIPU_API_KEY"
fi
export OPENAI_API_BASE="${OPENAI_API_BASE:-https://open.bigmodel.cn/api/paas/v4}"
export MSWEA_COST_TRACKING="${MSWEA_COST_TRACKING:-ignore_errors}"

cmd=("$PYTHON_BIN" "$ROOT_DIR/SWE-bench/run_swe_lite_official_case.py" "$@")

if [[ -n "${SWE_AGENT_CORE:-}" ]] && command -v taskset >/dev/null 2>&1; then
  exec taskset -c "$SWE_AGENT_CORE" "${cmd[@]}"
fi

exec "${cmd[@]}"
