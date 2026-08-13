#!/usr/bin/env bash
set -euo pipefail

CUNZHE_ROOT=${CUNZHE_ROOT:-/home/higon/cunzhe}
SUBMISSION=${AWS_SUBMISSION:-20250226_sweagent_claude-3-7-sonnet-20250219}
TRAJECTORY_DIR=${TRAJECTORY_DIR:-$CUNZHE_ROOT/swe_runs/aws_public_traces/$SUBMISSION}
EXTRA8_DIR=${EXTRA8_DIR:-$CUNZHE_ROOT/swe_flat_bundle_aws_extra8_20260812}
ASSET_DIR=${ASSET_DIR:-$CUNZHE_ROOT/swe_release_aws38_20260812}
PART_SIZE=${PART_SIZE:-1900m}
EXPECTED_MANIFEST_SHA256=${EXPECTED_MANIFEST_SHA256:-bbdbf338189873376b9e75b086f6387d6cc5999c866be1be49065dbb4c32e220}

command -v tar >/dev/null
command -v split >/dev/null
command -v sha256sum >/dev/null
command -v zstd >/dev/null

test -d "$TRAJECTORY_DIR"
test -f "$TRAJECTORY_DIR/aws38_manifest.json"
test -d "$EXTRA8_DIR"
test -f "$EXTRA8_DIR/manifest.json"
test -f "$EXTRA8_DIR/load_flat_bundle.py"

actual_manifest_sha256=$(sha256sum "$TRAJECTORY_DIR/aws38_manifest.json" | awk '{print $1}')
if [[ "$actual_manifest_sha256" != "$EXPECTED_MANIFEST_SHA256" ]]; then
  echo "Unexpected AWS-38 manifest SHA256: $actual_manifest_sha256" >&2
  exit 1
fi

if [[ -f "$ASSET_DIR/PREPARE_COMPLETE" ]]; then
  echo "Prepared assets already exist; verifying checksums."
  (cd "$ASSET_DIR" && sha256sum -c SHA256SUMS-AWS38-20260812)
  echo "ASSET_DIR=$ASSET_DIR"
  exit 0
fi

mkdir -p "$ASSET_DIR"
if find "$ASSET_DIR" -mindepth 1 -maxdepth 1 -print -quit | grep -q .; then
  echo "Incomplete/non-empty asset directory: $ASSET_DIR" >&2
  echo "Move it aside, then rerun this script." >&2
  exit 1
fi

extra8_parent=$(cd "$(dirname "$EXTRA8_DIR")" && pwd)
extra8_name=$(basename "$EXTRA8_DIR")
part_prefix="$ASSET_DIR/swe_aws38_extra8_images_20260812.tar.part."

echo "[1/4] Packing the eight incremental flat-rootfs images"
tar -C "$extra8_parent" -cf - "$extra8_name" \
  | split -b "$PART_SIZE" -a 3 - "$part_prefix"

echo "[2/4] Packing all 38 public AWS trajectories"
trajectory_parent=$(cd "$(dirname "$TRAJECTORY_DIR")" && pwd)
trajectory_name=$(basename "$TRAJECTORY_DIR")
trajectory_archive="$ASSET_DIR/swe_agent_aws38_trajectories_20260812.tar.zst"
tar -C "$trajectory_parent" -cf - "$trajectory_name" \
  | zstd -T4 -3 -o "$trajectory_archive"

cp "$TRAJECTORY_DIR/aws38_manifest.json" "$ASSET_DIR/aws38_manifest.json"

cat > "$ASSET_DIR/RESTORE-AWS38-20260812.txt" <<'EOF'
SWE-agent AWS-38 incremental release

This release contains:
  1. All 38 public AWS SWE-agent trajectories and aws38_manifest.json.
  2. The eight additional flat-rootfs images.

The original 30 flat-rootfs images remain in GitHub release:
  swe-images-20260727

Verify this incremental release:
  sha256sum -c SHA256SUMS-AWS38-20260812

Restore the eight additional flat-rootfs images under /home/higon/cunzhe:
  cat swe_aws38_extra8_images_20260812.tar.part.* \
    | tar -xf - -C /home/higon/cunzhe

Restore all 38 trajectories under /home/higon/cunzhe/swe_runs/aws_public_traces:
  zstd -dc swe_agent_aws38_trajectories_20260812.tar.zst \
    | tar -xf - -C /home/higon/cunzhe/swe_runs/aws_public_traces

Load the eight additional images:
  python3 /home/higon/cunzhe/swe_flat_bundle_aws_extra8_20260812/load_flat_bundle.py
EOF

echo "[3/4] Verifying archive structure"
cat "${part_prefix}"* | tar -tf - >/dev/null
zstd -t "$trajectory_archive"

echo "[4/4] Writing checksums"
(
  cd "$ASSET_DIR"
  sha256sum \
    swe_aws38_extra8_images_20260812.tar.part.* \
    swe_agent_aws38_trajectories_20260812.tar.zst \
    aws38_manifest.json \
    RESTORE-AWS38-20260812.txt \
    > SHA256SUMS-AWS38-20260812
  sha256sum -c SHA256SUMS-AWS38-20260812
)

date -u +'%Y-%m-%dT%H:%M:%SZ' > "$ASSET_DIR/PREPARE_COMPLETE"
part_count=$(find "$ASSET_DIR" -maxdepth 1 -type f -name 'swe_aws38_extra8_images_20260812.tar.part.*' | wc -l | tr -d ' ')
total_bytes=$(du -sb "$ASSET_DIR" | awk '{print $1}')
echo "PART_COUNT=$part_count"
echo "TOTAL_BYTES=$total_bytes"
echo "ASSET_DIR=$ASSET_DIR"
