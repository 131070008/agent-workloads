#!/usr/bin/env python3
"""Run SWE-agent replay with lifecycle and per-ToolCall timing probes."""

from __future__ import annotations

import atexit
import csv
import json
import os
import re
import sys
import time
import typing
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable

from typing_extensions import Self


# SWE-agent 1.0.0 imports typing.Self, which Python 3.10 does not provide.
typing.Self = Self


PROCESS_T0_NS = time.monotonic_ns()
PHASES: dict[str, list[int]] = defaultdict(list)
TOOLS: list[dict[str, Any]] = []
PARSES: list[int] = []
RUN_STARTED_NS: int | None = None
RUN_ENDED_NS: int | None = None


def elapsed_ns(t0: int) -> int:
    return time.monotonic_ns() - t0


def timed_method(cls: type, name: str, phase: str) -> None:
    original = getattr(cls, name)

    def wrapped(*args: Any, **kwargs: Any) -> Any:
        t0 = time.monotonic_ns()
        try:
            return original(*args, **kwargs)
        finally:
            PHASES[phase].append(elapsed_ns(t0))

    setattr(cls, name, wrapped)


def classify(action: str) -> str:
    command = action.strip()
    lower = command.lower()
    if re.search(r"(^|\s)(submit|submit_solution)(\s|$)", lower):
        return "submission"
    if lower.startswith("str_replace_editor create "):
        return "editor_create"
    if lower.startswith("str_replace_editor str_replace "):
        return "editor_replace"
    if lower.startswith("str_replace_editor "):
        return "editor_view"
    if re.search(r"(^|[;&|]\s*)(pip3?|python\s+-m\s+pip|apt-get|apt|conda|npm|yarn)\s+install\b", lower):
        return "package_install"
    if re.search(r"(^|[;&|]\s*)git\s+", lower):
        return "git"
    if re.search(r"(^|[;&|]\s*)(pytest|python\s+-m\s+pytest|tox|nox)\b", lower):
        return "test"
    if re.search(r"(^|[;&|]\s*)(python|python3)(\s|$)", lower):
        return "python"
    return "shell_other"


def tool_name(step: Any) -> str:
    calls = getattr(step, "tool_calls", None) or []
    if calls:
        return calls[0].get("function", {}).get("name", "")
    return "shell"


def ns_to_ms(value: int | float) -> float:
    return round(float(value) / 1_000_000.0, 3)


def install_probes() -> Callable[[], None]:
    from sweagent.agent.agents import DefaultAgent
    from sweagent.environment.swe_env import SWEEnv
    from sweagent.run.run_single import RunSingle
    from sweagent.tools.tools import ToolHandler

    original_run = RunSingle.run

    def run(self: Any, *args: Any, **kwargs: Any) -> Any:
        global RUN_STARTED_NS, RUN_ENDED_NS
        RUN_STARTED_NS = time.monotonic_ns()
        try:
            return original_run(self, *args, **kwargs)
        finally:
            RUN_ENDED_NS = time.monotonic_ns()

    RunSingle.run = run
    timed_method(SWEEnv, "start", "environment_start")
    timed_method(SWEEnv, "close", "environment_close")
    timed_method(DefaultAgent, "setup", "agent_setup")
    timed_method(DefaultAgent, "step", "step_total")
    timed_method(DefaultAgent, "add_step_to_history", "history_integrate")

    original_parse = ToolHandler.parse_actions

    def parse_actions(self: Any, *args: Any, **kwargs: Any) -> Any:
        t0 = time.monotonic_ns()
        try:
            return original_parse(self, *args, **kwargs)
        finally:
            PARSES.append(elapsed_ns(t0))

    ToolHandler.parse_actions = parse_actions

    original_handle_action = DefaultAgent.handle_action

    def handle_action(self: Any, step: Any, *args: Any, **kwargs: Any) -> Any:
        index = len(TOOLS) + 1
        action = getattr(step, "action", "") or ""
        t0 = time.monotonic_ns()
        result: Any = None
        error = ""
        try:
            result = original_handle_action(self, step, *args, **kwargs)
            return result
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            source = result if result is not None else step
            communicate_s = float(getattr(source, "execution_time", 0.0) or 0.0)
            observation = getattr(source, "observation", "") or ""
            record = {
                "tool_index": index,
                "tool_name": tool_name(source),
                "category": classify(action),
                "tool_e2e_ms": ns_to_ms(elapsed_ns(t0)),
                "communicate_ms": round(communicate_s * 1000.0, 3),
                "framework_tail_ms": 0.0,
                "output_bytes": len(observation.encode("utf-8", errors="replace")),
                "error": error,
                "command": action,
            }
            record["framework_tail_ms"] = round(
                max(0.0, record["tool_e2e_ms"] - record["communicate_ms"]), 3
            )
            TOOLS.append(record)

    DefaultAgent.handle_action = handle_action

    def restore() -> None:
        RunSingle.run = original_run
        ToolHandler.parse_actions = original_parse
        DefaultAgent.handle_action = original_handle_action

    return restore


def write_results() -> None:
    output_dir = Path(os.environ.get("SWE_TIMING_DIR", ".")).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    now_ns = time.monotonic_ns()
    full_wall_ns = now_ns - PROCESS_T0_NS
    main_ns = (RUN_ENDED_NS or now_ns) - (RUN_STARTED_NS or PROCESS_T0_NS)

    phase_ns = {name: sum(values) for name, values in PHASES.items()}
    step_ns = phase_ns.get("step_total", 0)
    measured_main_ns = (
        phase_ns.get("environment_start", 0)
        + phase_ns.get("agent_setup", 0)
        + step_ns
        + phase_ns.get("environment_close", 0)
    )
    summary = {
        "full_wall_ms": ns_to_ms(full_wall_ns),
        "main_total_ms": ns_to_ms(main_ns),
        "import_and_outer_ms": ns_to_ms(max(0, full_wall_ns - main_ns)),
        "environment_start_ms": ns_to_ms(phase_ns.get("environment_start", 0)),
        "agent_setup_ms": ns_to_ms(phase_ns.get("agent_setup", 0)),
        "step_total_ms": ns_to_ms(step_ns),
        "action_parse_ms": ns_to_ms(sum(PARSES)),
        "tool_and_submission_ms": round(sum(x["tool_e2e_ms"] for x in TOOLS), 3),
        "communicate_ms": round(sum(x["communicate_ms"] for x in TOOLS), 3),
        "history_integrate_ms": ns_to_ms(phase_ns.get("history_integrate", 0)),
        "environment_close_ms": ns_to_ms(phase_ns.get("environment_close", 0)),
        "other_main_ms": ns_to_ms(max(0, main_ns - measured_main_ns)),
        "step_residual_ms": round(
            max(
                0.0,
                ns_to_ms(step_ns)
                - sum(x["tool_e2e_ms"] for x in TOOLS)
                - ns_to_ms(sum(PARSES))
                - ns_to_ms(phase_ns.get("history_integrate", 0)),
            ),
            3,
        ),
        "tool_calls": len(TOOLS),
        "parse_calls": len(PARSES),
    }
    (output_dir / "timing_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
    )

    fields = [
        "tool_index", "tool_name", "category", "tool_e2e_ms", "communicate_ms",
        "framework_tail_ms", "output_bytes", "error", "command",
    ]
    with (output_dir / "tool_calls.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(TOOLS)

    categories: dict[str, dict[str, float]] = defaultdict(lambda: {"calls": 0, "tool_e2e_ms": 0.0})
    for item in TOOLS:
        categories[item["category"]]["calls"] += 1
        categories[item["category"]]["tool_e2e_ms"] += item["tool_e2e_ms"]
    with (output_dir / "category_summary.csv").open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["category", "calls", "tool_e2e_ms", "share_percent"])
        total = summary["tool_and_submission_ms"] or 1.0
        for name, values in sorted(categories.items(), key=lambda x: -x[1]["tool_e2e_ms"]):
            writer.writerow([
                name,
                int(values["calls"]),
                round(values["tool_e2e_ms"], 3),
                round(values["tool_e2e_ms"] / total * 100.0, 3),
            ])


def main() -> None:
    atexit.register(write_results)
    install_probes()
    from sweagent.run.run import main as sweagent_main

    sweagent_main()


if __name__ == "__main__":
    main()
