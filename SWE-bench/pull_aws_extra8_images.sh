#!/usr/bin/env bash
set -euo pipefail

OUTPUT_DIR=${OUTPUT_DIR:-/home/higon/cunzhe/swe_runs/aws38_prepare}
mkdir -p "$OUTPUT_DIR"

images=(
  docker.io/swebench/sweb.eval.x86_64.django_1776_django-12915:latest
  docker.io/swebench/sweb.eval.x86_64.sympy_1776_sympy-22840:latest
  docker.io/swebench/sweb.eval.x86_64.sympy_1776_sympy-11870:latest
  docker.io/swebench/sweb.eval.x86_64.sympy_1776_sympy-20049:latest
  docker.io/swebench/sweb.eval.x86_64.sympy_1776_sympy-12481:latest
  docker.io/swebench/sweb.eval.x86_64.sympy_1776_sympy-12419:latest
  docker.io/swebench/sweb.eval.x86_64.sympy_1776_sympy-22714:latest
  docker.io/swebench/sweb.eval.x86_64.sympy_1776_sympy-20212:latest
)

for image in "${images[@]}"; do
  if docker image inspect "$image" >/dev/null 2>&1; then
    printf '[%s] already present %s\n' "$(date '+%F %T')" "$image"
    continue
  fi
  until docker pull --platform linux/amd64 "$image"; do
    printf '[%s] retry %s in 15s\n' "$(date '+%F %T')" "$image"
    sleep 15
  done
done

for image in "${images[@]}"; do
  docker image inspect "$image" --format '{{.Id}} {{.Os}}/{{.Architecture}} {{.Size}} {{index .RepoDigests 0}}'
done > "$OUTPUT_DIR/extra8_images.txt"

printf 'images=8 completed_at=%s\n' "$(date --iso-8601=seconds)" \
  > "$OUTPUT_DIR/EXTRA8_IMAGES_COMPLETE"
