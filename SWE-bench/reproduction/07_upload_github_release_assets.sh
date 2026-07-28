#!/usr/bin/env bash
set -euo pipefail

ASSET_DIR=${1:-/Users/cztian/workspace/myself/agent/image_artifacts/swe_flat_bundle_20260727_release}
REPOSITORY=${GITHUB_REPOSITORY:-131070008/agent-workloads}
TAG=${GITHUB_RELEASE_TAG:-swe-images-20260727}
MAX_ATTEMPTS=${MAX_ATTEMPTS:-5}

command -v gh >/dev/null
gh auth status >/dev/null
test -f "$ASSET_DIR/SHA256SUMS"
test -f "$ASSET_DIR/RESTORE.txt"

if ! gh release view "$TAG" --repo "$REPOSITORY" >/dev/null 2>&1; then
  gh release create "$TAG" \
    --repo "$REPOSITORY" \
    --target main \
    --title "SWE 30-case image bundle (20260727)" \
    --notes "Private offline image bundle for the fixed 30-case SWE Golden replay. Download every asset, verify SHA256SUMS, then follow RESTORE.txt."
fi

upload_files=()
while IFS= read -r file; do
  upload_files+=("$file")
done < <(
  find "$ASSET_DIR" -maxdepth 1 -type f \
    \( -name '*.tar.part.*' -o -name 'SHA256SUMS' -o -name 'RESTORE.txt' \) \
    | sort
)

for file in "${upload_files[@]}"; do
  name=$(basename "$file")
  if gh release view "$TAG" --repo "$REPOSITORY" --json assets \
      --jq '.assets[].name' | grep -Fqx "$name"; then
    echo "SKIP existing asset: $name"
    continue
  fi

  attempt=1
  while ! gh release upload "$TAG" "$file" --repo "$REPOSITORY"; do
    if (( attempt >= MAX_ATTEMPTS )); then
      echo "Upload failed after $MAX_ATTEMPTS attempts: $name" >&2
      exit 1
    fi
    echo "Retry $attempt/$MAX_ATTEMPTS: $name" >&2
    attempt=$((attempt + 1))
    sleep 10
  done
done

gh release view "$TAG" --repo "$REPOSITORY" --json url --jq '.url'
