#!/usr/bin/env bash
set -euo pipefail

TARGET=${1:?Usage: $0 <target-ssh-host> [source-root] [target-root]}
SOURCE_ROOT=${2:-/home/higon/cunzhe}
TARGET_ROOT=${3:-/home/higon/cunzhe}

ssh "$TARGET" "mkdir -p '$TARGET_ROOT/swe_runs/golden_replay'"

rsync -aH --info=progress2 --partial --append-verify \
  "$SOURCE_ROOT/swe_flat_bundle_20260727/" \
  "$TARGET:$TARGET_ROOT/swe_flat_bundle_20260727/"

rsync -aH --info=progress2 --partial --append-verify \
  --exclude '.secrets/' \
  --exclude '*.env' \
  "$SOURCE_ROOT/agent-workloads/" \
  "$TARGET:$TARGET_ROOT/agent-workloads/"

rsync -aH --info=progress2 --partial --append-verify \
  "$SOURCE_ROOT/swe_runs/golden_replay/flash/" \
  "$TARGET:$TARGET_ROOT/swe_runs/golden_replay/flash/"

echo "Transfer complete: $TARGET:$TARGET_ROOT"
