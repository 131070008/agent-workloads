#!/usr/bin/env bash
set -euo pipefail

SOURCE_DIR=${1:-/Users/cztian/workspace/myself/agent/image_artifacts/swe_flat_bundle_20260727}
ASSET_DIR=${2:-/Users/cztian/workspace/myself/agent/image_artifacts/swe_flat_bundle_20260727_release}
PART_SIZE=${PART_SIZE:-1900m}

test -d "$SOURCE_DIR"
test -f "$SOURCE_DIR/PACKAGE_COMPLETE"
test -f "$SOURCE_DIR/manifest.json"
test -f "$SOURCE_DIR/load_flat_bundle.py"

source_parent=$(cd "$(dirname "$SOURCE_DIR")" && pwd)
source_name=$(basename "$SOURCE_DIR")
mkdir -p "$ASSET_DIR"

part_prefix="$ASSET_DIR/${source_name}.tar.part."
if compgen -G "${part_prefix}*" >/dev/null; then
  echo "Release parts already exist in $ASSET_DIR"
  echo "Move them aside before rebuilding a new bundle."
  exit 1
fi

echo "Creating release parts from $SOURCE_DIR"
tar -C "$source_parent" -cf - "$source_name" \
  | split -b "$PART_SIZE" -a 3 - "$part_prefix"

if command -v sha256sum >/dev/null 2>&1; then
  (cd "$ASSET_DIR" && sha256sum "${source_name}.tar.part."*) \
    > "$ASSET_DIR/SHA256SUMS"
else
  (cd "$ASSET_DIR" && shasum -a 256 "${source_name}.tar.part."*) \
    > "$ASSET_DIR/SHA256SUMS"
fi

cat > "$ASSET_DIR/RESTORE.txt" <<EOF
SWE flat-rootfs bundle: $source_name

Verify all downloaded assets:
  shasum -a 256 -c SHA256SUMS

Restore the original directory:
  cat ${source_name}.tar.part.* | tar -xf -

The restored directory contains manifest.json, load_flat_bundle.py and the
30 compressed rootfs images expected by SWE-bench/reproduction.
EOF

echo "Checking concatenated tar stream"
cat "${part_prefix}"* | tar -tf - >/dev/null

part_count=$(find "$ASSET_DIR" -maxdepth 1 -type f -name "${source_name}.tar.part.*" | wc -l | tr -d ' ')
total_size=$(du -sh "$ASSET_DIR" | awk '{print $1}')
echo "PART_COUNT=$part_count"
echo "TOTAL_SIZE=$total_size"
echo "ASSET_DIR=$ASSET_DIR"
