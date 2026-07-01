#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WA_DIR="$ROOT_DIR/workloads/WorkArena/upstream/WorkArena"

cd "$WA_DIR"

python -m pip install -e .
python -m playwright install chromium

python - <<'PY'
from browsergym.workarena import ATOMIC_TASKS

print(f"WorkArena atomic tasks: {len(ATOMIC_TASKS)}")
print("Import check passed.")
PY
