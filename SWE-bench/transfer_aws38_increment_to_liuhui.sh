#!/usr/bin/env bash
set -euo pipefail

REMOTE=higon@192.168.250.74
KEY=/home/higon/.ssh/id_ed25519_liuhui_transfer
RSYNC_RSH="ssh -i $KEY -o ServerAliveInterval=30 -o ServerAliveCountMax=20"
export RSYNC_RSH

TRAJECTORY_DIR=/home/higon/cunzhe/swe_runs/aws_public_traces/20250226_sweagent_claude-3-7-sonnet-20250219/
TRAJECTORY_TARGET=$REMOTE:/home/higon/cunzhe/swe_runs/aws_public_traces/20250226_sweagent_claude-3-7-sonnet-20250219/
IMAGE_DIR=/home/higon/cunzhe/swe_flat_bundle_aws_extra8_20260812/
IMAGE_TARGET=$REMOTE:/home/higon/cunzhe/swe_flat_bundle_aws_extra8_20260812/

ssh -i "$KEY" "$REMOTE" \
  'mkdir -p /home/higon/cunzhe/swe_runs/aws_public_traces/20250226_sweagent_claude-3-7-sonnet-20250219 /home/higon/cunzhe/swe_flat_bundle_aws_extra8_20260812'

until rsync -a --partial --append-verify --info=progress2 \
  "$TRAJECTORY_DIR" "$TRAJECTORY_TARGET"; do
  printf '[%s] trajectory rsync interrupted; resume in 15s\n' "$(date '+%F %T')"
  sleep 15
done

until rsync -a --partial --append-verify --info=progress2 \
  "$IMAGE_DIR" "$IMAGE_TARGET"; do
  printf '[%s] image rsync interrupted; resume in 15s\n' "$(date '+%F %T')"
  sleep 15
done

printf '[%s] AWS-38 increment transfer complete\n' "$(date '+%F %T')"
