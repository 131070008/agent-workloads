#!/usr/bin/env bash
set -euo pipefail

SUBMISSION=20250226_sweagent_claude-3-7-sonnet-20250219
BASE_URL="https://swe-bench-submissions.s3.amazonaws.com/lite/$SUBMISSION/trajs"
OUTPUT_DIR=${OUTPUT_DIR:-/home/higon/cunzhe/swe_runs/aws_public_traces/$SUBMISSION}

objects=(
  django__django-12915/django__django-12915.config.yaml
  django__django-12915/django__django-12915.pred
  django__django-12915/django__django-12915.traj
  sympy__sympy-22840/sympy__sympy-22840.config.yaml
  sympy__sympy-22840/sympy__sympy-22840.pred
  sympy__sympy-22840/sympy__sympy-22840.traj
  sympy__sympy-11870/sympy__sympy-11870.config.yaml
  sympy__sympy-11870/sympy__sympy-11870.pred
  sympy__sympy-11870/sympy__sympy-11870.traj
  sympy__sympy-20049/sympy__sympy-20049.config.yaml
  sympy__sympy-20049/sympy__sympy-20049.patch
  sympy__sympy-20049/sympy__sympy-20049.pred
  sympy__sympy-20049/sympy__sympy-20049.traj
  sympy__sympy-12481/sympy__sympy-12481.config.yaml
  sympy__sympy-12481/sympy__sympy-12481.patch
  sympy__sympy-12481/sympy__sympy-12481.pred
  sympy__sympy-12481/sympy__sympy-12481.traj
  sympy__sympy-12419/sympy__sympy-12419.config.yaml
  sympy__sympy-12419/sympy__sympy-12419.pred
  sympy__sympy-12419/sympy__sympy-12419.traj
  sympy__sympy-22714/sympy__sympy-22714.config.yaml
  sympy__sympy-22714/sympy__sympy-22714.patch
  sympy__sympy-22714/sympy__sympy-22714.pred
  sympy__sympy-22714/sympy__sympy-22714.traj
  sympy__sympy-20212/sympy__sympy-20212.config.yaml
  sympy__sympy-20212/sympy__sympy-20212.patch
  sympy__sympy-20212/sympy__sympy-20212.pred
  sympy__sympy-20212/sympy__sympy-20212.traj
)

mkdir -p "$OUTPUT_DIR"

for object in "${objects[@]}"; do
  destination="$OUTPUT_DIR/$object"
  marker="$destination.done"
  mkdir -p "$(dirname "$destination")"
  [[ -f "$marker" ]] && continue

  until /usr/bin/curl --http1.1 -fL -C - \
    --connect-timeout 30 \
    --speed-time 120 \
    --speed-limit 1024 \
    -o "$destination" \
    "$BASE_URL/$object"; do
    printf '[%s] retry %s in 10s\n' "$(date '+%F %T')" "$object"
    sleep 10
  done
  touch "$marker"
  printf '[%s] complete %s\n' "$(date '+%F %T')" "$object"
done

printf 'cases=8 objects=%d completed_at=%s\n' "${#objects[@]}" "$(date --iso-8601=seconds)" \
  > "$OUTPUT_DIR/EXTRA8_DOWNLOAD_COMPLETE"
