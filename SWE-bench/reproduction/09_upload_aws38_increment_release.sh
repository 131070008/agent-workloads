#!/usr/bin/env bash
set -euo pipefail

ASSET_DIR=${ASSET_DIR:-/home/higon/cunzhe/swe_release_aws38_20260812}
REPOSITORY=${GITHUB_REPOSITORY:-131070008/agent-workloads}
TAG=${GITHUB_RELEASE_TAG:-swe-aws38-20260812}
RETRY_DELAY=${RETRY_DELAY:-30}

command -v gh >/dev/null
gh auth status >/dev/null
test -f "$ASSET_DIR/PREPARE_COMPLETE"
test -f "$ASSET_DIR/SHA256SUMS-AWS38-20260812"
test -f "$ASSET_DIR/RESTORE-AWS38-20260812.txt"

(cd "$ASSET_DIR" && sha256sum -c SHA256SUMS-AWS38-20260812)

if ! gh release view "$TAG" --repo "$REPOSITORY" >/dev/null 2>&1; then
  gh release create "$TAG" \
    --repo "$REPOSITORY" \
    --target main \
    --title "SWE-agent AWS-38 replay assets (20260812)" \
    --notes-file "$ASSET_DIR/RESTORE-AWS38-20260812.txt"
fi

mapfile -t upload_files < <(
  find "$ASSET_DIR" -maxdepth 1 -type f \
    \( -name 'swe_aws38_extra8_images_20260812.tar.part.*' \
       -o -name 'swe_agent_aws38_trajectories_20260812.tar.zst' \
       -o -name 'aws38_manifest.json' \
       -o -name 'SHA256SUMS-AWS38-20260812' \
       -o -name 'RESTORE-AWS38-20260812.txt' \) \
    | sort
)

remote_assets() {
  gh release view "$TAG" --repo "$REPOSITORY" --json assets \
    --jq '.assets[] | [.name, .size] | @tsv'
}

for file in "${upload_files[@]}"; do
  name=$(basename "$file")
  local_size=$(stat -c '%s' "$file")

  while true; do
    remote_size=$(remote_assets | awk -F '\t' -v name="$name" '$1 == name {print $2; exit}')
    if [[ "$remote_size" == "$local_size" ]]; then
      echo "SKIP complete asset: $name ($local_size bytes)"
      break
    fi
    if [[ -n "$remote_size" ]]; then
      echo "Remote asset has the same name but a different size: $name" >&2
      echo "local=$local_size remote=$remote_size" >&2
      exit 1
    fi

    echo "UPLOAD $name ($local_size bytes)"
    if gh release upload "$TAG" "$file" --repo "$REPOSITORY"; then
      continue
    fi
    echo "Upload interrupted; retrying $name in ${RETRY_DELAY}s" >&2
    sleep "$RETRY_DELAY"
  done
done

expected_count=${#upload_files[@]}
verified_count=0
for file in "${upload_files[@]}"; do
  name=$(basename "$file")
  local_size=$(stat -c '%s' "$file")
  remote_size=$(remote_assets | awk -F '\t' -v name="$name" '$1 == name {print $2; exit}')
  [[ "$remote_size" == "$local_size" ]]
  verified_count=$((verified_count + 1))
done

[[ "$verified_count" -eq "$expected_count" ]]
date -u +'%Y-%m-%dT%H:%M:%SZ' > "$ASSET_DIR/UPLOAD_COMPLETE"
echo "VERIFIED_ASSETS=$verified_count"
gh release view "$TAG" --repo "$REPOSITORY" --json url --jq '.url'
