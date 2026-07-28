#!/usr/bin/env bash
set -euo pipefail

# Classify page faults by Linux MM handling path on a CPU set.
# This intentionally uses a system-wide CPU scope. On the current Ubuntu 5.15
# kernel, combining kprobe events with perf --for-each-cgroup can hang perf.

CPUS=${PAGE_FAULT_CPUS:-0-7}
DURATION_SECONDS=${PAGE_FAULT_SECONDS:-30}
OUTPUT_ROOT=${PAGE_FAULT_OUTPUT_ROOT:-/home/higon/cunzhe/swe_runs/page_fault_types}
PASS_FILE=${PERF_SUDO_PASS_FILE:-/home/higon/cunzhe/.secrets/passwd}
STAMP=$(date +%Y%m%d_%H%M%S)
OUTPUT_DIR=${PAGE_FAULT_OUTPUT_DIR:-$OUTPUT_ROOT/page_fault_types_$STAMP}
PREFIX="swepf_${$}"

mkdir -p "$OUTPUT_DIR"

if [[ $EUID -eq 0 ]]; then
  SUDO=()
else
  if ! sudo -n true 2>/dev/null; then
    if [[ ! -r "$PASS_FILE" ]]; then
      echo "sudo is required and password file is not readable: $PASS_FILE" >&2
      exit 1
    fi
    sudo -S -p '' -v < "$PASS_FILE"
  fi
  SUDO=(sudo -n)
fi

declare -a PROBES=(
  "${PREFIX}_handle=handle_mm_fault"
  "${PREFIX}_anon=do_anonymous_page"
  "${PREFIX}_cow=do_wp_page"
  "${PREFIX}_file=do_fault"
  "${PREFIX}_swap=do_swap_page"
  "${PREFIX}_thp=do_huge_pmd_anonymous_page"
)
declare -a EVENTS=()

cleanup() {
  local probe
  for probe in "${EVENTS[@]}"; do
    "${SUDO[@]}" perf probe -d "$probe" >/dev/null 2>&1 || true
  done
}
trap cleanup EXIT INT TERM

for definition in "${PROBES[@]}"; do
  name=${definition%%=*}
  "${SUDO[@]}" perf probe -a "$definition" >/dev/null
  EVENTS+=("$name")
done

EVENT_LIST="page-faults,minor-faults,major-faults"
for name in "${EVENTS[@]}"; do
  EVENT_LIST+=",probe:$name"
done

cat > "$OUTPUT_DIR/metadata.txt" <<EOF
timestamp=$STAMP
hostname=$(hostname)
kernel=$(uname -r)
cpus=$CPUS
duration_seconds=$DURATION_SECONDS
scope=CPU-system-wide
warning=kprobe events are intentionally not combined with perf --for-each-cgroup
handle=all handle_mm_fault entries
anon=anonymous first-touch faults
cow=write-protect/COW faults
file=file-backed VMA faults
swap=swap faults
thp=transparent huge-page anonymous faults
EOF

"${SUDO[@]}" perf stat \
  -a -C "$CPUS" \
  --no-big-num \
  -x, \
  -e "$EVENT_LIST" \
  -o "$OUTPUT_DIR/fault_types.csv" \
  -- sleep "$DURATION_SECONDS"

echo "OUTPUT_DIR=$OUTPUT_DIR"
echo "RAW=$OUTPUT_DIR/fault_types.csv"
echo "META=$OUTPUT_DIR/metadata.txt"
