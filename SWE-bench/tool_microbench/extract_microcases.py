#!/usr/bin/env python3
"""Build a standalone microbenchmark bundle from SWE-agent trajectories and images."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent


def run(
    command: list[str],
    *,
    check: bool = True,
    text: bool = True,
    stdout: Any = subprocess.PIPE,
) -> subprocess.CompletedProcess:
    return subprocess.run(
        command,
        check=check,
        text=text,
        stdout=stdout,
        stderr=subprocess.PIPE,
    )


def parse_trajectory_args(values: list[str]) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for value in values:
        instance_id, separator, path = value.partition("=")
        if not separator or not instance_id or not path:
            raise ValueError(f"Invalid --trajectory value: {value!r}; expected INSTANCE_ID=/path/file.local.traj")
        trajectory = Path(path).expanduser().resolve()
        if not trajectory.is_file():
            raise FileNotFoundError(trajectory)
        result[instance_id] = trajectory
    return result


def docker_json(*args: str) -> Any:
    completed = run(["docker", *args])
    return json.loads(completed.stdout)


def copy_testbed(image: str, destination: Path) -> None:
    container_name = f"swe-tool-microbench-{uuid.uuid4().hex[:12]}"
    container_id = run(["docker", "create", "--name", container_name, image, "/bin/true"]).stdout.strip()
    try:
        destination.mkdir(parents=True)
        run(["docker", "cp", f"{container_id}:/testbed/.", str(destination)], stdout=None)
    finally:
        subprocess.run(["docker", "rm", "-f", container_id], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def materialize(image: str, command: str, destination: Path) -> dict[str, Any]:
    completed = run(
        ["docker", "run", "--rm", "--network=none", image, "sh", "-lc", command],
        check=False,
        text=False,
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(completed.stdout)
    stderr_path = destination.with_suffix(destination.suffix + ".stderr")
    stderr_path.write_bytes(completed.stderr)
    if completed.returncode != 0:
        raise RuntimeError(
            f"Materialization failed for {image}: {command!r}; exit={completed.returncode}; "
            f"stderr={completed.stderr.decode(errors='replace')[:1000]}"
        )
    return {
        "command": command,
        "stdout": str(destination.relative_to(destination.parents[1])),
        "stderr": str(stderr_path.relative_to(stderr_path.parents[1])),
        "exit_code": completed.returncode,
    }


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_hash_manifest(bundle: Path) -> None:
    output = bundle / "SHA256SUMS"
    lines: list[str] = []
    for path in sorted(bundle.rglob("*")):
        if path.is_file() and path != output:
            lines.append(f"{sha256(path)}  {path.relative_to(bundle)}")
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selection", type=Path, default=SCRIPT_DIR / "selection.json")
    parser.add_argument("--trajectory", action="append", default=[], metavar="INSTANCE_ID=PATH")
    parser.add_argument("--editor-source", type=Path, required=True, help="SWE-agent tools/edit_anthropic directory")
    parser.add_argument("--registry-source", type=Path, help="SWE-agent tools/registry/lib directory")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    selection_path = args.selection.expanduser().resolve()
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    trajectories = parse_trajectory_args(args.trajectory)
    required_instances = set(selection["instances"])
    missing = sorted(required_instances - set(trajectories))
    if missing:
        parser.error(f"Missing --trajectory entries for: {', '.join(missing)}")

    output_dir = args.output_dir.expanduser().resolve()
    if output_dir.exists():
        parser.error(f"Output already exists; choose a new directory: {output_dir}")
    output_dir.mkdir(parents=True)

    editor_source = args.editor_source.expanduser().resolve()
    registry_source = (
        args.registry_source.expanduser().resolve()
        if args.registry_source
        else editor_source.parent / "registry" / "lib"
    )
    if not (editor_source / "bin" / "str_replace_editor").is_file():
        parser.error(f"Missing editor executable under {editor_source}")
    if not (registry_source / "registry.py").is_file():
        parser.error(f"Missing registry.py under {registry_source}")

    loaded: dict[str, dict[str, Any]] = {}
    source_records: dict[str, list[dict[str, Any]]] = {}
    for instance_id, path in trajectories.items():
        loaded[instance_id] = json.loads(path.read_text(encoding="utf-8"))
        source_records[instance_id] = []

    manifest_cases: list[dict[str, Any]] = []
    for selected in selection["cases"]:
        instance_id = selected["instance_id"]
        index = int(selected["action_index"])
        trajectory = loaded[instance_id]["trajectory"]
        if index < 1 or index > len(trajectory):
            raise IndexError(f"{selected['id']}: action {index} outside trajectory length {len(trajectory)}")
        record = trajectory[index - 1]
        action = record["action"]
        if selected["family"] == "grep" and "grep" not in action:
            raise ValueError(f"{selected['id']}: selected action is not a grep command: {action}")
        if selected["family"] == "editor" and not action.startswith("str_replace_editor "):
            raise ValueError(f"{selected['id']}: selected action is not an editor command: {action}")
        case = dict(selected)
        case["image"] = selection["instances"][instance_id]["image"]
        case["source_action"] = action
        case["source_execution_time_seconds"] = record.get("execution_time")
        case["source_observation"] = record.get("observation", "")
        manifest_cases.append(case)
        source_records[instance_id].append(
            {
                "action_index": index,
                "action": action,
                "observation": record.get("observation", ""),
                "execution_time": record.get("execution_time"),
                "state": record.get("state"),
            }
        )

    image_metadata: dict[str, Any] = {}
    for instance_id, instance in selection["instances"].items():
        image = instance["image"]
        inspect = docker_json("image", "inspect", image)
        image_metadata[instance_id] = inspect[0]
        copy_testbed(image, output_dir / "fixtures" / instance_id / "testbed")

    generated: dict[str, Any] = {}
    for case in manifest_cases:
        if case["strategy"] != "materialized_stdin":
            continue
        relative = Path(case["materialized_file"])
        generated[case["id"]] = materialize(
            case["image"],
            case["materialize_command"],
            output_dir / relative,
        )

    shutil.copytree(editor_source, output_dir / "editor_tool" / "edit_anthropic")
    (output_dir / "editor_tool" / "registry").mkdir(parents=True)
    shutil.copy2(registry_source / "registry.py", output_dir / "editor_tool" / "registry" / "registry.py")

    provenance_dir = output_dir / "provenance"
    provenance_dir.mkdir()
    shutil.copy2(selection_path, provenance_dir / "selection.json")
    for instance_id, path in trajectories.items():
        (provenance_dir / f"{instance_id}.selected_actions.json").write_text(
            json.dumps(source_records[instance_id], ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    manifest = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "builder": str(Path(__file__).resolve()),
        "host": {
            "hostname": platform.node(),
            "platform": platform.platform(),
            "python": sys.version,
        },
        "trajectory_framework": {
            "name": "SWE-agent",
            "version": sorted({str(data.get("info", {}).get("swe_agent_version")) for data in loaded.values()}),
            "swe_rex_version": sorted({str(data.get("info", {}).get("swe_rex_version")) for data in loaded.values()}),
            "note": "The model was Claude, but these are SWE-agent trajectories, not Claude Code trajectories."
        },
        "trajectories": {key: str(value) for key, value in trajectories.items()},
        "images": image_metadata,
        "generated_inputs": generated,
        "editor_tool": {
            "source": str(editor_source),
            "implementation": "SWE-agent edit_anthropic/str_replace_editor",
            "filemap_disabled_for_standalone": True,
            "note": "Selected full-view input is below 16 KB; disabling file-map does not change this case."
        },
        "cases": manifest_cases,
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    shutil.copy2(SCRIPT_DIR / "run_microcases.py", output_dir / "run_microcases.py")
    shutil.copy2(SCRIPT_DIR / "README.md", output_dir / "README.md")
    write_hash_manifest(output_dir)

    print(f"BUNDLE={output_dir}")
    print(f"CASES={len(manifest_cases)}")
    print(f"FIXTURES={len(selection['instances'])}")


if __name__ == "__main__":
    main()
