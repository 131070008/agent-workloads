#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

HARBOR_BIN="${HARBOR_BIN:-/Users/cztian/.local/bin/harbor}"
TB_DATASET_DIR="${TB_DATASET_DIR:-workloads/Terminal-Bench/upstream/terminal-bench-2}"
TB_TASK="${TB_TASK:-fix-git}"

export HTTP_PROXY="${HTTP_PROXY:-http://127.0.0.1:7897}"
export HTTPS_PROXY="${HTTPS_PROXY:-http://127.0.0.1:7897}"

"$HARBOR_BIN" run \
  -p "$TB_DATASET_DIR/$TB_TASK" \
  -a oracle \
  -n 1 \
  -o workloads/Terminal-Bench/results \
  --yes \
  --ve "HTTP_PROXY=${TB_VERIFIER_HTTP_PROXY:-http://192.168.5.2:7897}" \
  --ve "HTTPS_PROXY=${TB_VERIFIER_HTTPS_PROXY:-http://192.168.5.2:7897}"
