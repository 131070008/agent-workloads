#!/usr/bin/env bash
set -euo pipefail

SOURCE=${SOURCE:-/home/higon/cunzhe/swe_flat_bundle_20260727/}
TARGET=${TARGET:-higon@192.168.250.74:/home/higon/cunzhe/swe_flat_bundle_20260727/}
KEY=${KEY:-/home/higon/.ssh/id_ed25519_liuhui_transfer}
REMOTE=higon@192.168.250.74
RSYNC_RSH="ssh -i $KEY -o ServerAliveInterval=30 -o ServerAliveCountMax=20"
export RSYNC_RSH

ssh -i "$KEY" -o ServerAliveInterval=30 -o ServerAliveCountMax=20 \
  "$REMOTE" 'mkdir -p /home/higon/cunzhe/swe_flat_bundle_20260727'

until rsync -a --partial --append-verify --info=progress2 "$SOURCE" "$TARGET"; do
  printf '[%s] rsync interrupted; resume in 15s\n' "$(date '+%F %T')"
  sleep 15
done

printf '[%s] transfer complete\n' "$(date '+%F %T')"
