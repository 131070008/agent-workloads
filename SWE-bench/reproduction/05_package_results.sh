#!/usr/bin/env bash
set -euo pipefail

RUN_DIR=${1:?Usage: $0 <golden-run-directory> [output-directory]}
RUN_DIR=$(realpath "$RUN_DIR")
OUTPUT_DIR=${2:-$(dirname "$RUN_DIR")}
OUTPUT_DIR=$(realpath "$OUTPUT_DIR")
RUN_NAME=$(basename "$RUN_DIR")
ARCHIVE=$OUTPUT_DIR/$RUN_NAME.tar.zst

test -f "$RUN_DIR/controller_returncode.txt"
test -f "$RUN_DIR/k1/performance_summary.json"
test -f "$RUN_DIR/k16/performance_summary.json"
mkdir -p "$OUTPUT_DIR"

tar -C "$(dirname "$RUN_DIR")" -I 'zstd -T0 -3' -cf "$ARCHIVE" "$RUN_NAME"
sha256sum "$ARCHIVE" > "$ARCHIVE.sha256"

echo "ARCHIVE=$ARCHIVE"
echo "CHECKSUM=$ARCHIVE.sha256"
