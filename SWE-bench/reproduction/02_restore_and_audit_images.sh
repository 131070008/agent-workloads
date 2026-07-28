#!/usr/bin/env bash
set -euo pipefail

CUNZHE_ROOT=${CUNZHE_ROOT:-/home/higon/cunzhe}
BUNDLE_DIR=${BUNDLE_DIR:-$CUNZHE_ROOT/swe_flat_bundle_20260727}
PARALLEL_IMPORTS=${PARALLEL_IMPORTS:-4}
SKIP_ARCHIVE_HASH=${SKIP_ARCHIVE_HASH:-0}
STAMP=$(date +%Y%m%d_%H%M%S)
OUTPUT_DIR=${OUTPUT_DIR:-$CUNZHE_ROOT/swe_runs/image_restore_$STAMP}

test -f "$BUNDLE_DIR/PACKAGE_COMPLETE"
test -f "$BUNDLE_DIR/manifest.json"
test -f "$BUNDLE_DIR/load_flat_bundle.py"
command -v docker >/dev/null
command -v zstd >/dev/null
docker info >/dev/null
mkdir -p "$OUTPUT_DIR"

mapfile -t indexes < <(python3 - "$BUNDLE_DIR/manifest.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    manifest = json.load(stream)
indexes = [entry["index"] for entry in manifest["images"]]
if len(indexes) != 30:
    raise SystemExit(f"expected 30 images, found {len(indexes)}")
print("\n".join(str(index) for index in indexes))
PY
)

loader_args=(--bundle-dir "$BUNDLE_DIR")
if [[ "$SKIP_ARCHIVE_HASH" == 1 ]]; then
  loader_args+=(--skip-hash)
fi

printf '%s\n' "${indexes[@]}" | xargs -P "$PARALLEL_IMPORTS" -I{} \
  python3 "$BUNDLE_DIR/load_flat_bundle.py" "${loader_args[@]}" --only-index {} \
  2>&1 | tee "$OUTPUT_DIR/import.log"

python3 "$BUNDLE_DIR/load_flat_bundle.py" \
  --bundle-dir "$BUNDLE_DIR" \
  --skip-hash \
  --verify-existing \
  2>&1 | tee "$OUTPUT_DIR/final_audit.log"

image_count=$(docker image ls --format '{{.Repository}}:{{.Tag}}' \
  | grep -c '^swebench/sweb.eval.x86_64' || true)
printf 'SWE_IMAGE_COUNT=%s\n' "$image_count" | tee "$OUTPUT_DIR/summary.txt"
test "$image_count" -eq 30

echo "Image restore and audit complete: $OUTPUT_DIR"
