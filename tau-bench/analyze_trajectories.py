#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Analyze tau-bench historical trajectories without invoking an LLM."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from statistics import mean
from typing import Any


def load_json(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise TypeError(f"expected a list of trajectories, got {type(data).__name__}")
    return data


def message_tool_names(message: dict[str, Any]) -> list[str]:
    names: list[str] = []
    if message.get("role") == "tool":
        name = message.get("name")
        if isinstance(name, str):
            names.append(name)

    tool_calls = message.get("tool_calls")
    if isinstance(tool_calls, list):
        for call in tool_calls:
            if not isinstance(call, dict):
                continue
            function = call.get("function")
            if isinstance(function, dict) and isinstance(function.get("name"), str):
                names.append(function["name"])
            elif isinstance(call.get("name"), str):
                names.append(call["name"])
    return names


def summarize(records: list[dict[str, Any]], limit: int | None) -> dict[str, Any]:
    selected = records[:limit] if limit else records
    if not selected:
        raise ValueError("no trajectories selected")

    role_counts: Counter[str] = Counter()
    tool_counts: Counter[str] = Counter()
    traj_lengths: list[int] = []
    user_turns: list[int] = []
    assistant_turns: list[int] = []
    tool_turns: list[int] = []
    rewards: list[float] = []
    gt_actions: Counter[str] = Counter()

    for item in selected:
        traj = item.get("traj", [])
        if not isinstance(traj, list):
            continue

        traj_lengths.append(len(traj))
        rewards.append(float(item.get("reward", 0.0) or 0.0))

        local_roles: Counter[str] = Counter()
        for message in traj:
            if not isinstance(message, dict):
                continue
            role = str(message.get("role", "<missing>"))
            role_counts[role] += 1
            local_roles[role] += 1
            tool_counts.update(message_tool_names(message))

        user_turns.append(local_roles["user"])
        assistant_turns.append(local_roles["assistant"])
        tool_turns.append(local_roles["tool"])

        task = item.get("info", {}).get("task", {})
        for action in task.get("actions", []) if isinstance(task, dict) else []:
            if isinstance(action, dict) and isinstance(action.get("name"), str):
                gt_actions[action["name"]] += 1

    return {
        "tasks": len(selected),
        "reward_mean": mean(rewards),
        "reward_pass_count": sum(1 for r in rewards if r > 0),
        "trajectory_messages_mean": mean(traj_lengths),
        "trajectory_messages_min": min(traj_lengths),
        "trajectory_messages_max": max(traj_lengths),
        "user_turns_mean": mean(user_turns),
        "assistant_turns_mean": mean(assistant_turns),
        "tool_turns_mean": mean(tool_turns),
        "role_counts": role_counts,
        "tool_counts": tool_counts,
        "ground_truth_actions": gt_actions,
    }


def print_summary(summary: dict[str, Any], top_n: int) -> None:
    print("TAU-BENCH HISTORICAL TRAJECTORY SMOKE")
    print("=" * 72)
    print(f"tasks analyzed: {summary['tasks']}")
    print(
        "reward/pass: "
        f"mean={summary['reward_mean']:.3f}, "
        f"pass_count={summary['reward_pass_count']}/{summary['tasks']}"
    )
    print(
        "messages/task: "
        f"mean={summary['trajectory_messages_mean']:.1f}, "
        f"min={summary['trajectory_messages_min']}, "
        f"max={summary['trajectory_messages_max']}"
    )
    print(
        "turns/task: "
        f"user={summary['user_turns_mean']:.1f}, "
        f"assistant={summary['assistant_turns_mean']:.1f}, "
        f"tool_result={summary['tool_turns_mean']:.1f}"
    )

    print("\nrole counts:")
    for role, count in summary["role_counts"].most_common():
        print(f"  {role}: {count}")

    print("\ntop tool calls:")
    if summary["tool_counts"]:
        for name, count in summary["tool_counts"].most_common(top_n):
            print(f"  {name}: {count}")
    else:
        print("  <none>")

    print("\ntop ground-truth target actions:")
    for name, count in summary["ground_truth_actions"].most_common(top_n):
        print(f"  {name}: {count}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        type=Path,
        default=Path(__file__).parent
        / "datasets"
        / "historical_trajectories"
        / "gpt-4o-airline.json",
    )
    parser.add_argument("--max-tasks", type=int, default=20)
    parser.add_argument("--top-n", type=int, default=12)
    args = parser.parse_args()

    records = load_json(args.input)
    summary = summarize(records, args.max_tasks)
    print_summary(summary, args.top_n)


if __name__ == "__main__":
    main()
