#!/usr/bin/env python3
"""Build the minimal Claude Code-style tool microbenchmark from SWE artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import shlex
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
IMAGES = {
    "django__django-14608": "swebench/sweb.eval.x86_64.django_1776_django-14608:v1",
    "pytest-dev__pytest-5221": "swebench/sweb.eval.x86_64.pytest-dev_1776_pytest-5221:v1",
}


def run(command: list[str], *, check: bool = True, stdout: Any = subprocess.PIPE) -> subprocess.CompletedProcess:
    return subprocess.run(command, check=check, text=True, stdout=stdout, stderr=subprocess.PIPE)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_trajectories(values: list[str]) -> dict[str, Path]:
    parsed: dict[str, Path] = {}
    for value in values:
        instance_id, separator, raw_path = value.partition("=")
        if not separator or instance_id not in IMAGES:
            raise ValueError(f"Invalid --trajectory: {value}")
        path = Path(raw_path).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(path)
        parsed[instance_id] = path
    missing = sorted(set(IMAGES) - set(parsed))
    if missing:
        raise ValueError(f"Missing trajectories: {', '.join(missing)}")
    return parsed


def selected_record(loaded: dict[str, Any], one_based_index: int) -> dict[str, Any]:
    trajectory = loaded["trajectory"]
    if not 1 <= one_based_index <= len(trajectory):
        raise IndexError(one_based_index)
    return trajectory[one_based_index - 1]


def option(tokens: list[str], name: str) -> str:
    try:
        return tokens[tokens.index(name) + 1]
    except (ValueError, IndexError) as error:
        raise ValueError(f"Missing {name} in action: {shlex.join(tokens)}") from error


def copy_from_image(image: str, paths: list[tuple[str, Path]]) -> dict[str, Any]:
    name = f"cc-tool-microbench-{uuid.uuid4().hex[:12]}"
    container = run(["docker", "create", "--name", name, image, "/bin/true"]).stdout.strip()
    try:
        for source, destination in paths:
            destination.mkdir(parents=True)
            run(["docker", "cp", f"{container}:{source}/.", str(destination)], stdout=None)
    finally:
        subprocess.run(["docker", "rm", "-f", container], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    inspected = json.loads(run(["docker", "image", "inspect", image]).stdout)[0]
    return {
        "reference": image,
        "image_id": inspected.get("Id"),
        "repo_digests": inspected.get("RepoDigests", []),
        "architecture": inspected.get("Architecture"),
        "os": inspected.get("Os"),
    }


def relative_fixture_hashes(bundle: Path) -> dict[str, str]:
    return {
        str(path.relative_to(bundle)): sha256(path)
        for path in sorted((bundle / "fixtures").rglob("*"))
        if path.is_file()
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trajectory", action="append", default=[], metavar="INSTANCE_ID=PATH")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    trajectories = parse_trajectories(args.trajectory)
    output = args.output_dir.expanduser().resolve()
    if output.exists():
        parser.error(f"Output already exists: {output}")
    output.mkdir(parents=True)

    loaded = {
        instance_id: json.loads(path.read_text(encoding="utf-8"))
        for instance_id, path in trajectories.items()
    }

    django = loaded["django__django-14608"]
    pytest = loaded["pytest-dev__pytest-5221"]
    records = {
        "grep_single": selected_record(django, 14),
        "grep_context": selected_record(pytest, 9),
        "grep_recursive": selected_record(pytest, 3),
        "grep_files": selected_record(django, 5),
        "read_full": selected_record(django, 12),
        "read_range": selected_record(django, 9),
        "write_create": selected_record(django, 16),
        "edit_unique": selected_record(django, 18),
    }

    expected_fragments = {
        "grep_single": 'grep -n "nonfield" /testbed/django/forms/forms.py',
        "grep_context": 'grep -n "def showfixtures" -A 20',
        "grep_recursive": 'grep -r "def _fixtures"',
        "grep_files": 'xargs grep -l "FormSet"',
        "read_full": "str_replace_editor view /testbed/django/forms/utils.py",
        "read_range": "str_replace_editor view /testbed/django/forms/formsets.py",
        "write_create": "str_replace_editor create /testbed/reproduce.py",
        "edit_unique": "str_replace_editor str_replace /testbed/django/forms/formsets.py",
    }
    for key, fragment in expected_fragments.items():
        action = records[key].get("action", "")
        if fragment not in action:
            raise ValueError(f"Trajectory action drift for {key}: {action}")

    image_metadata = {
        "django__django-14608": copy_from_image(
            IMAGES["django__django-14608"],
            [("/testbed/django/forms", output / "fixtures" / "django" / "forms")],
        ),
        "pytest-dev__pytest-5221": copy_from_image(
            IMAGES["pytest-dev__pytest-5221"],
            [("/testbed/src/_pytest", output / "fixtures" / "pytest" / "_pytest")],
        ),
    }

    write_tokens = shlex.split(records["write_create"]["action"])
    edit_tokens = shlex.split(records["edit_unique"]["action"])
    write_content = option(write_tokens, "--file_text")
    old_string = option(edit_tokens, "--old_str")
    new_string = option(edit_tokens, "--new_str")

    payloads = output / "payloads"
    payloads.mkdir()
    (payloads / "reproduce.py").write_text(write_content, encoding="utf-8")
    (payloads / "edit_old.txt").write_text(old_string, encoding="utf-8")
    (payloads / "edit_new.txt").write_text(new_string, encoding="utf-8")

    formsets = output / "fixtures" / "django" / "forms" / "formsets.py"
    source_formsets = formsets.read_text(encoding="utf-8")
    if source_formsets.count(old_string) != 1:
        raise ValueError("The selected edit old_string is not unique in the image fixture")
    edited_formsets = source_formsets.replace(old_string, new_string)

    cases = [
        {
            "id": "read_full",
            "tool": "Read",
            "description": "Read and line-number a complete 5.9 KB Django source file.",
            "fixture": "fixtures/django/forms/utils.py",
            "offset": 1,
            "limit": None,
            "expected_source_sha256": sha256(output / "fixtures" / "django" / "forms" / "utils.py"),
            "source_instance": "django__django-14608",
            "source_action_index": 12,
        },
        {
            "id": "read_range",
            "tool": "Read",
            "description": "Read and line-number lines 290-298 from Django formsets.py.",
            "fixture": "fixtures/django/forms/formsets.py",
            "offset": 290,
            "limit": 9,
            "expected_source_sha256": sha256(formsets),
            "source_instance": "django__django-14608",
            "source_action_index": 9,
        },
        {
            "id": "write_create",
            "tool": "Write",
            "description": "Create reproduce.py with the exact trajectory payload.",
            "content_file": "payloads/reproduce.py",
            "expected_sha256": hashlib.sha256(write_content.encode()).hexdigest(),
            "source_instance": "django__django-14608",
            "source_action_index": 16,
        },
        {
            "id": "edit_unique",
            "tool": "Edit",
            "description": "Read-first, validate one exact match, and rewrite formsets.py.",
            "fixture": "fixtures/django/forms/formsets.py",
            "old_string_file": "payloads/edit_old.txt",
            "new_string_file": "payloads/edit_new.txt",
            "replace_all": False,
            "expected_sha256": hashlib.sha256(edited_formsets.encode()).hexdigest(),
            "source_instance": "django__django-14608",
            "source_action_index": 18,
        },
    ]

    grep_commands = [
        {
            "id": "grep_single_file",
            "description": "Search one Django source file with line numbers.",
            "command": "grep -n \"nonfield\" \"$B/fixtures/django/forms/forms.py\"",
            "source_action": records["grep_single"]["action"],
            "source_instance": "django__django-14608",
            "source_action_index": 14,
        },
        {
            "id": "grep_context",
            "description": "Search pytest python.py and return 20 trailing context lines.",
            "command": "grep -n \"def showfixtures\" -A 20 --include=\"*.py\" \"$B/fixtures/pytest/_pytest/python.py\"",
            "source_action": records["grep_context"]["action"],
            "source_instance": "pytest-dev__pytest-5221",
            "source_action_index": 9,
        },
        {
            "id": "grep_recursive_include",
            "description": "Recursively search the real _pytest subtree with a Python glob.",
            "command": "grep -r \"def _fixtures\" --include=\"*.py\" \"$B/fixtures/pytest/_pytest\"",
            "source_action": records["grep_recursive"]["action"],
            "source_instance": "pytest-dev__pytest-5221",
            "source_action_index": 3,
        },
        {
            "id": "grep_find_xargs",
            "description": "Find Python files, search their contents, filter test paths, and keep ten results.",
            "command": "find \"$B/fixtures/django/forms\" -type f -name \"*.py\" -print0 | xargs -0 grep -l \"FormSet\" | grep -v \"test\" | head -10",
            "source_action": records["grep_files"]["action"],
            "source_instance": "django__django-14608",
            "source_action_index": 5,
        },
    ]

    cc_rg_commands = [
        {
            "id": "cc_rg_single_file",
            "description": "CC Grep content mode on one Django source file.",
            "command": "node \"$B/cc_rg_tool.mjs\" --pattern nonfield --path \"$B/fixtures/django/forms/forms.py\" --output-mode content",
        },
        {
            "id": "cc_rg_context",
            "description": "CC Grep content mode with 20 trailing context lines.",
            "command": "node \"$B/cc_rg_tool.mjs\" --pattern 'def showfixtures' --path \"$B/fixtures/pytest/_pytest/python.py\" --glob '*.py' --output-mode content -A 20",
        },
        {
            "id": "cc_rg_recursive",
            "description": "CC Grep recursive search with a Python glob.",
            "command": "node \"$B/cc_rg_tool.mjs\" --pattern 'def _fixtures' --path \"$B/fixtures/pytest/_pytest\" --glob '*.py' --output-mode content",
        },
        {
            "id": "cc_rg_files",
            "description": "CC Grep files-with-matches mode, mtime sort, and result limit.",
            "command": "node \"$B/cc_rg_tool.mjs\" --pattern FormSet --path \"$B/fixtures/django/forms\" --glob '*.py' --output-mode files_with_matches --head-limit 10",
        },
    ]

    provenance = output / "provenance"
    provenance.mkdir()
    action_summaries = {
        "grep_single": records["grep_single"]["action"],
        "grep_context": records["grep_context"]["action"],
        "grep_recursive": records["grep_recursive"]["action"],
        "grep_files": records["grep_files"]["action"],
        "read_full": records["read_full"]["action"],
        "read_range": records["read_range"]["action"],
        "write_create": "str_replace_editor create /testbed/reproduce.py --file_text <payloads/reproduce.py>",
        "edit_unique": "str_replace_editor str_replace /testbed/django/forms/formsets.py --old_str <payloads/edit_old.txt> --new_str <payloads/edit_new.txt>",
    }
    source_indexes = {
        "grep_single": ("django__django-14608", 14),
        "grep_context": ("pytest-dev__pytest-5221", 9),
        "grep_recursive": ("pytest-dev__pytest-5221", 3),
        "grep_files": ("django__django-14608", 5),
        "read_full": ("django__django-14608", 12),
        "read_range": ("django__django-14608", 9),
        "write_create": ("django__django-14608", 16),
        "edit_unique": ("django__django-14608", 18),
    }
    selected_actions = {
        "schema_version": 1,
        "description": "Selected action metadata used to derive the standalone inputs.",
        "actions": [
            {
                "id": key,
                "source_instance": source_indexes[key][0],
                "source_action_index": source_indexes[key][1],
                "action_summary": action_summaries[key],
                "execution_time_seconds": records[key].get("execution_time"),
            }
            for key in records
        ],
    }
    (provenance / "selected_actions.json").write_text(
        json.dumps(selected_actions, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    shutil.copy2(SCRIPT_DIR / "cc_tool_microbench.mjs", output / "cc_tool_microbench.mjs")
    shutil.copy2(SCRIPT_DIR / "cc_file_tool.mjs", output / "cc_file_tool.mjs")
    shutil.copy2(SCRIPT_DIR / "cc_rg_tool.mjs", output / "cc_rg_tool.mjs")
    shutil.copy2(SCRIPT_DIR / "README.md", output / "README.md")
    shutil.copy2(SCRIPT_DIR / "source_audit.json", output / "source_audit.json")

    manifest = {
        "schema_version": 2,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": {
            "trajectory_framework": "SWE-agent 1.0.0 with SWE-ReX 1.1.0",
            "instances": sorted(trajectories),
            "image_artifacts": image_metadata,
            "note": "Source artifacts are only required to regenerate fixtures; normal execution uses the committed files.",
        },
        "tool_semantics": "Claude Code 2.1.88 core Read/Write/Edit/Grep behavior plus original GNU grep trajectory commands",
        "fixture_sha256": relative_fixture_hashes(output),
        "payload_files": {
            "write_content": "payloads/reproduce.py",
            "edit_old_string": "payloads/edit_old.txt",
            "edit_new_string": "payloads/edit_new.txt",
        },
        "cases": cases,
        "grep_commands": grep_commands,
        "cc_rg_commands": cc_rg_commands,
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    hash_lines = []
    for path in sorted(output.rglob("*")):
        if path.is_file() and path.name != "SHA256SUMS":
            hash_lines.append(f"{sha256(path)}  {path.relative_to(output)}")
    (output / "SHA256SUMS").write_text("\n".join(hash_lines) + "\n", encoding="utf-8")

    print(f"BUNDLE={output}")
    print(f"CASES={len(cases)}")
    print(f"GREP_COMMANDS={len(grep_commands)}")
    print(f"CC_RG_COMMANDS={len(cc_rg_commands)}")
    print(f"FIXTURE_FILES={len(manifest['fixture_sha256'])}")


if __name__ == "__main__":
    main()
