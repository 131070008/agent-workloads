#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 INSTANCE_ID" >&2
  exit 2
fi

INSTANCE_ID=$1
CUNZHE_ROOT=${CUNZHE_ROOT:-/home/higon/cunzhe}
SUBMISSION=${AWS_SUBMISSION:-20250226_sweagent_claude-3-7-sonnet-20250219}
TRAJECTORY_ROOT=${TRAJECTORY_ROOT:-$CUNZHE_ROOT/swe_runs/aws_public_traces/$SUBMISSION}
MANIFEST=${AWS38_MANIFEST:-$TRAJECTORY_ROOT/aws38_manifest.json}
SWEAGENT_SOURCE=${SWEAGENT_SOURCE:-$CUNZHE_ROOT/swe-agent-v1.0.0-src}
SWEAGENT_VENV=${SWEAGENT_VENV:-$CUNZHE_ROOT/sweagent-v1.0.0-venv}
SHARED_REX=${SHARED_REX:-$CUNZHE_ROOT/swerex-runtime-1.1.0-shared}
TOOL_WHEELHOUSE=${TOOL_WHEELHOUSE:-$CUNZHE_ROOT/swe-tool-wheelhouse-v1.0.0}
OUTPUT_ROOT=${OUTPUT_ROOT:-$CUNZHE_ROOT/swe_runs/aws38_replay}
SWE_CPUSET=${SWE_CPUSET:-}

test -f "$MANIFEST"
test -d "$SWEAGENT_SOURCE/tools"
test -x "$SWEAGENT_VENV/bin/python"
test -x "$SHARED_REX/bin/swerex-remote"
test -d "$TOOL_WHEELHOUSE"

case_data=$(INSTANCE_ID="$INSTANCE_ID" MANIFEST="$MANIFEST" python3 - <<'PY'
import json
import os

instance_id = os.environ["INSTANCE_ID"]
manifest = json.load(open(os.environ["MANIFEST"]))
case = next((item for item in manifest["cases"] if item["instance_id"] == instance_id), None)
if case is None:
    raise SystemExit(f"Unknown AWS-38 instance: {instance_id}")
print(case["trajectory"])
print(case["step_count"])
print(case["recorded_tool_seconds"])
PY
)

trajectory_rel=$(sed -n '1p' <<<"$case_data")
recorded_trajectory_entries=$(sed -n '2p' <<<"$case_data")
recorded_tool_seconds=$(sed -n '3p' <<<"$case_data")
source_traj="$TRAJECTORY_ROOT/$trajectory_rel"
test -f "$source_traj"
image=$(SOURCE_TRAJ="$source_traj" python3 - <<'PY'
import json
import os

data = json.load(open(os.environ["SOURCE_TRAJ"]))
config = data["replay_config"]
if isinstance(config, str):
    config = json.loads(config)
print(config["env"]["deployment"]["image"].removeprefix("docker.io/"))
PY
)
docker image inspect "$image" >/dev/null

timestamp=$(date +%Y%m%d_%H%M%S)
output_dir="$OUTPUT_ROOT/${INSTANCE_ID}_${timestamp}"
mkdir -p "$output_dir"
printf '%s\n' "$output_dir" > "$OUTPUT_ROOT/LATEST"
local_traj="$output_dir/$INSTANCE_ID.local.traj"

SOURCE_TRAJ="$source_traj" \
DEST_TRAJ="$local_traj" \
SWEAGENT_SOURCE="$SWEAGENT_SOURCE" \
SHARED_REX="$SHARED_REX" \
TOOL_WHEELHOUSE="$TOOL_WHEELHOUSE" \
SWE_CPUSET="$SWE_CPUSET" \
python3 - <<'PY'
import json
import os

source = os.environ["SOURCE_TRAJ"]
dest = os.environ["DEST_TRAJ"]
sweagent_source = os.environ["SWEAGENT_SOURCE"]
shared_rex = os.environ["SHARED_REX"]
tool_wheelhouse = os.environ["TOOL_WHEELHOUSE"]
cpu_set = os.environ.get("SWE_CPUSET", "")

data = json.load(open(source))
config = data["replay_config"]
was_string = isinstance(config, str)
if was_string:
    config = json.loads(config)

# Public AWS trajectories can end with a harness status message such as
# "Exit due to cost limit" followed by "Exited (autosubmitted)". It is not an
# action, but SWE-agent 1.0.0 replay incorrectly requires every assistant
# message to contain a ToolCall. Drop only this known non-action sentinel.
terminal_statuses = {"Exit due to cost limit"}
data["history"] = [
    message
    for message in data["history"]
    if not (
        message.get("role") == "assistant"
        and not message.get("tool_calls")
        and message.get("content") in terminal_statuses
    )
]

old_tools = "/home/klieret/SWE-agent/tools/"
new_tools = f"{sweagent_source}/tools/"
for bundle in config["agent"]["tools"]["bundles"]:
    if bundle["path"].startswith(old_tools):
        bundle["path"] = new_tools + bundle["path"][len(old_tools):]

deployment = config["env"]["deployment"]
deployment["pull"] = "never"
docker_args = deployment.setdefault("docker_args", [])
docker_args.extend([
    f"--volume={shared_rex}:/opt/swerex-runtime:ro",
    f"--volume={tool_wheelhouse}:/opt/swe-tool-wheelhouse:ro",
    "--env=PATH=/opt/swerex-runtime/bin:/opt/miniconda3/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    "--env=PIP_NO_INDEX=1",
    "--env=PIP_FIND_LINKS=/opt/swe-tool-wheelhouse",
])
if cpu_set:
    docker_args.append(f"--cpuset-cpus={cpu_set}")

data["replay_config"] = json.dumps(config) if was_string else config
with open(dest, "w") as handle:
    json.dump(data, handle)
PY

start_epoch=$(date +%s.%N)
set +e
(
  cd "$SWEAGENT_SOURCE"
  if [[ -n "${SWE_TIMING_PROBE:-}" ]]; then
    SWE_TIMING_DIR="$output_dir" PYTHONPATH="$SWEAGENT_SOURCE" /usr/bin/time -v \
      "$SWEAGENT_VENV/bin/python" "$SWE_TIMING_PROBE" \
      run-replay \
      --traj_path "$local_traj" \
      --output_dir "$output_dir/replay"
  else
    PYTHONPATH="$SWEAGENT_SOURCE" /usr/bin/time -v \
      "$SWEAGENT_VENV/bin/python" -c \
      'import typing; from typing_extensions import Self; typing.Self=Self; from sweagent.run.run import main; main()' \
      run-replay \
      --traj_path "$local_traj" \
      --output_dir "$output_dir/replay"
  fi
) >"$output_dir/replay.log" 2>"$output_dir/time_and_stderr.log"
exit_code=$?
set -e
end_epoch=$(date +%s.%N)

# SWE-ReX normally removes the container. Explicit cleanup handles setup or
# ToolCall failures without affecting containers from other cases.
while IFS= read -r container_id; do
  [[ -z "$container_id" ]] || docker kill "$container_id" >/dev/null 2>&1 || true
done < <(docker ps -q --filter "ancestor=$image")

wall_seconds=$(START="$start_epoch" END="$end_epoch" python3 - <<'PY'
import os
print(f"{float(os.environ['END']) - float(os.environ['START']):.6f}")
PY
)

cat > "$output_dir/summary.tsv" <<EOF
instance_id	$INSTANCE_ID
image	$image
recorded_trajectory_entries	$recorded_trajectory_entries
recorded_tool_seconds	$recorded_tool_seconds
wall_seconds	$wall_seconds
exit_code	$exit_code
output_dir	$output_dir
EOF

cat "$output_dir/summary.tsv"
exit "$exit_code"
