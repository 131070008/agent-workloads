#!/usr/bin/env bash
set -euo pipefail

CUNZHE_ROOT=${CUNZHE_ROOT:-/home/higon/cunzhe}
WORKLOAD_ROOT=$CUNZHE_ROOT/agent-workloads
GOLDEN_DIR=$CUNZHE_ROOT/swe_runs/golden_replay/flash
BUNDLE_DIR=$CUNZHE_ROOT/swe_flat_bundle_20260727
PYTHON=$WORKLOAD_ROOT/.venv-swe/bin/python

echo '=== Platform ==='
hostname
uname -a
lscpu
free -h
df -h "$CUNZHE_ROOT" /var/lib/docker

echo '=== Docker ==='
id
docker version
docker info --format 'driver={{.Driver}} cgroup={{.CgroupDriver}} version={{.CgroupVersion}} root={{.DockerRootDir}}'
test -z "$(docker ps -q)"

echo '=== Golden set ==='
test -x "$PYTHON"
test -f "$GOLDEN_DIR/manifest.json"
test -f "$BUNDLE_DIR/manifest.json"
mini_version=$("$PYTHON" -c 'import importlib.metadata; print(importlib.metadata.version("mini-swe-agent"))')
echo "mini_swe_agent_version=$mini_version"
test "$mini_version" = '2.4.4'
python3 - "$GOLDEN_DIR/manifest.json" "$BUNDLE_DIR/manifest.json" <<'PY'
import json
import sys

for path, label in [(sys.argv[1], "trajectory"), (sys.argv[2], "image")]:
    with open(path, encoding="utf-8") as stream:
        data = json.load(stream)
    entries = data.get("cases") or data.get("images") or data.get("instances")
    if entries is None:
        raise SystemExit(f"cannot find entries in {path}")
    print(f"{label}_count={len(entries)}")
    if len(entries) != 30:
        raise SystemExit(f"expected 30 {label} entries")
PY

echo '=== Runner hashes ==='
(
  cd "$WORKLOAD_ROOT/SWE-bench"
  sha256sum -c - <<'EOF'
4bdff122db346e04e6ddd44e895487cd9ea3a8a0347da5efc74c5c8ba0a08ee2  run_swe_golden_fixed_sweep.sh
7f03e3316bf4d2ff50b6193724df177644613ee151c4b97d97a8867c9a36ed81  run_swe_golden_multi_perf.sh
a723bbf12d26505c248c1c20b2806d0eb3573fdd1a0e24221a111544fc25fd7d  run_swe_golden_replay.py
f3b5331df93083fe9b5506458e40851443b945dbd87271a5bf769110ce365298  replay_swe_trajectory.py
ce043d2ac4fe4a425187468426e901ce637539d47bb2a9b39ea5ad38681f4fbd  compare_swe_golden_concurrency.py
EOF
)
printf '%s  %s\n' \
  '5e4cf50386f3fa01679ba2f0607a8d4023acc7c102f996aa339b56d164ce7c9c' \
  "$GOLDEN_DIR/manifest.json" \
  | sha256sum -c -

echo '=== Images ==='
python3 "$BUNDLE_DIR/load_flat_bundle.py" \
  --bundle-dir "$BUNDLE_DIR" \
  --skip-hash \
  --verify-existing

echo 'Environment validation passed.'
