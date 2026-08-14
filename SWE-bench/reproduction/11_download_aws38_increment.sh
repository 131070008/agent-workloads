#!/usr/bin/env bash
set -euo pipefail

ACTION=${1:-download}
DATA_ROOT=${DATA_ROOT:-/data/cunzhe}
DOWNLOAD_DIR=${DOWNLOAD_DIR:-$DATA_ROOT/swe_aws38_increment_20260812}
REPOSITORY=${GITHUB_REPOSITORY:-131070008/agent-workloads}
TAG=${GITHUB_RELEASE_TAG:-swe-aws38-20260812}
BASE_URL=${GITHUB_RELEASE_BASE_URL:-https://github.com/$REPOSITORY/releases/download/$TAG}
PROXY=${HTTPS_PROXY:-${https_proxy:-}}

FILES=(
  RESTORE-AWS38-20260812.txt
  SHA256SUMS-AWS38-20260812
  aws38_manifest.json
  swe_agent_aws38_trajectories_20260812.tar.zst
  swe_aws38_extra8_images_20260812.tar.part.aaa
  swe_aws38_extra8_images_20260812.tar.part.aab
  swe_aws38_extra8_images_20260812.tar.part.aac
  swe_aws38_extra8_images_20260812.tar.part.aad
  swe_aws38_extra8_images_20260812.tar.part.aae
)

download() {
  mkdir -p "$DOWNLOAD_DIR"
  cd "$DOWNLOAD_DIR"

  curl_args=(
    --http1.1
    --location
    --fail
    --show-error
    --connect-timeout 30
    --speed-time 120
    --speed-limit 1024
    --continue-at -
  )
  [[ -z "$PROXY" ]] || curl_args+=(--proxy "$PROXY")

  for file in "${FILES[@]}"; do
    if [[ -f "$file.done" ]]; then
      echo "SKIP complete: $file"
      continue
    fi

    echo "START/RESUME: $file"
    until /usr/bin/curl "${curl_args[@]}" --output "$file" "$BASE_URL/$file"; do
      echo "RETRY in 15s: $file" >&2
      sleep 15
    done
    touch "$file.done"
  done
}

verify() {
  cd "$DOWNLOAD_DIR"
  sha256sum -c SHA256SUMS-AWS38-20260812
}

restore() {
  verify
  mkdir -p "$DATA_ROOT/swe_runs/aws_public_traces"

  cat "$DOWNLOAD_DIR"/swe_aws38_extra8_images_20260812.tar.part.* \
    | tar -xf - -C "$DATA_ROOT"
  zstd -dc "$DOWNLOAD_DIR/swe_agent_aws38_trajectories_20260812.tar.zst" \
    | tar -xf - -C "$DATA_ROOT/swe_runs/aws_public_traces"

  echo "EXTRA8_IMAGES=$DATA_ROOT/swe_flat_bundle_aws_extra8_20260812"
  echo "AWS38_TRACES=$DATA_ROOT/swe_runs/aws_public_traces/20250226_sweagent_claude-3-7-sonnet-20250219"
  echo "Load images with:"
  echo "  sudo python3 $DATA_ROOT/swe_flat_bundle_aws_extra8_20260812/load_flat_bundle.py --bundle-dir $DATA_ROOT/swe_flat_bundle_aws_extra8_20260812"
}

case "$ACTION" in
  download)
    download
    ;;
  verify)
    verify
    ;;
  restore)
    restore
    ;;
  all)
    download
    restore
    ;;
  *)
    echo "Usage: $0 {download|verify|restore|all}" >&2
    exit 2
    ;;
esac
