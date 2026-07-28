#!/usr/bin/env python3
"""Compare two SWE Golden manifests at model-decision and workload levels."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import median
from typing import Any


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def ratio(numerator: float, denominator: float) -> float | None:
    return numerator / denominator if denominator else None


def summarize(manifest: dict[str, Any]) -> dict[str, Any]:
    cases = manifest["cases"]
    actions = [case["metrics"]["replayable_action_count"] for case in cases]
    api_calls = [case["metrics"]["api_calls"] for case in cases]
    arrival = [case["metrics"]["arrival_gap_sum_seconds"] for case in cases]
    command = [case["metrics"]["command_time_sum_seconds"] for case in cases]
    submitted = sum(case["metrics"]["exit_status"] == "Submitted" for case in cases)
    resolved = sum((case.get("evaluator") or {}).get("resolved_instances") == 1 for case in cases)
    return {
        "label": manifest.get("label"),
        "cases": len(cases),
        "api_calls": sum(api_calls),
        "actions": sum(actions),
        "actions_per_api_call": ratio(sum(actions), sum(api_calls)),
        "median_actions_per_case": median(actions) if actions else None,
        "non_action_calls": sum(case["metrics"]["non_action_model_calls"] for case in cases),
        "submitted": submitted,
        "resolved_with_available_metadata": resolved,
        "total_tokens": sum(case["metrics"]["token_usage"]["total_tokens"] for case in cases),
        "recorded_arrival_gap_seconds": sum(arrival),
        "recorded_command_wall_seconds": sum(command),
        "command_wall_duty_proxy": ratio(sum(command), sum(command) + sum(arrival)),
    }


def summarize_replay(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    summary = read_json(path.expanduser().resolve())
    jobs = summary.get("jobs") or []
    exact_passes = 0
    semantic_passes = 0
    returncode_drift = []
    semantic_failures = []
    for job in jobs:
        validation = job.get("validation") or {}
        checks = validation.get("checks") or {}
        exact = bool(validation.get("strict_pass", all(checks.values()) if checks else False))
        semantic = bool(
            validation.get(
                "semantic_pass",
                checks.get("commands_match")
                and checks.get("exit_status_match")
                and checks.get("patch_match"),
            )
        )
        exact_passes += int(exact)
        semantic_passes += int(semantic)
        if semantic and not checks.get("returncodes_match"):
            returncode_drift.append(job.get("instance_id"))
        if not semantic:
            semantic_failures.append(job.get("instance_id"))
    return {
        "summary_file": str(path.expanduser().resolve()),
        "jobs": len(jobs),
        "exact_passes": exact_passes,
        "semantic_passes": semantic_passes,
        "returncode_drift_instances": sorted(filter(None, returncode_drift)),
        "semantic_failure_instances": sorted(filter(None, semantic_failures)),
    }


def fmt(value: Any) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, float):
        return f"{value:.3f}"
    return f"{value:,}" if isinstance(value, int) else str(value)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--left", type=Path, required=True)
    parser.add_argument("--right", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--left-replay-summary", type=Path)
    parser.add_argument("--right-replay-summary", type=Path)
    args = parser.parse_args()
    left = read_json(args.left.expanduser().resolve())
    right = read_json(args.right.expanduser().resolve())
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    left_summary = summarize(left)
    right_summary = summarize(right)

    left_cases = {case["instance_id"]: case for case in left["cases"]}
    right_cases = {case["instance_id"]: case for case in right["cases"]}
    paired = []
    for instance_id in sorted(left_cases.keys() & right_cases.keys()):
        left_metrics = left_cases[instance_id]["metrics"]
        right_metrics = right_cases[instance_id]["metrics"]
        paired.append(
            {
                "instance_id": instance_id,
                "left_actions": left_metrics["replayable_action_count"],
                "right_actions": right_metrics["replayable_action_count"],
                "action_delta": right_metrics["replayable_action_count"] - left_metrics["replayable_action_count"],
                "left_exit": left_metrics["exit_status"],
                "right_exit": right_metrics["exit_status"],
                "same_patch": left_metrics["patch_sha256"] == right_metrics["patch_sha256"],
            }
        )

    left_replay = summarize_replay(args.left_replay_summary)
    right_replay = summarize_replay(args.right_replay_summary)
    output = {
        "left": left_summary,
        "right": right_summary,
        "replay_validation": {"left": left_replay, "right": right_replay},
        "paired_cases": paired,
    }
    (output_dir / "comparison.json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    metrics = [
        ("case 数", "cases"),
        ("API calls", "api_calls"),
        ("可回放 tool actions", "actions"),
        ("actions/API call", "actions_per_api_call"),
        ("每 case action 中位数", "median_actions_per_case"),
        ("无 tool action 的模型调用", "non_action_calls"),
        ("Submitted", "submitted"),
        ("已有 evaluator 元数据中的 resolved", "resolved_with_available_metadata"),
        ("total tokens", "total_tokens"),
        ("记录到的模型动作间隔总和/s", "recorded_arrival_gap_seconds"),
        ("记录到的工具墙钟时间总和/s", "recorded_command_wall_seconds"),
        ("工具墙钟占空比代理", "command_wall_duty_proxy"),
    ]
    lines = [
        "# SWE Golden Set 对比",
        "",
        f"| 指标 | {left_summary['label']} | {right_summary['label']} |",
        "|---|---:|---:|",
    ]
    lines.extend(
        f"| {label} | {fmt(left_summary[key])} | {fmt(right_summary[key])} |" for label, key in metrics
    )
    lines.extend(
        [
            "",
            "> 工具墙钟占空比只表示 Agent 轨迹在工具阶段停留的时间比例，不等于 CPU 利用率。",
            "> CPU 反压必须结合同平台 replay 的吞吐、cgroup CPU time、PMU 和并发队列长度判断。",
        ]
    )
    if left_replay or right_replay:
        lines.extend(
            [
                "",
                "## Replay 验证",
                "",
                f"| 指标 | {left_summary['label']} | {right_summary['label']} |",
                "|---|---:|---:|",
                f"| Jobs | {fmt(left_replay.get('jobs'))} | {fmt(right_replay.get('jobs'))} |",
                f"| Semantic pass | {fmt(left_replay.get('semantic_passes'))} | {fmt(right_replay.get('semantic_passes'))} |",
                f"| Exact pass | {fmt(left_replay.get('exact_passes'))} | {fmt(right_replay.get('exact_passes'))} |",
                f"| Return-code drift | {fmt(len(left_replay.get('returncode_drift_instances', [])))} | {fmt(len(right_replay.get('returncode_drift_instances', [])))} |",
                "",
                "> Semantic 要求命令序列、退出状态和 patch 一致；Exact 额外要求逐命令 return code 一致。",
            ]
        )
        if left_replay.get("returncode_drift_instances"):
            lines.append(
                f"> {left_summary['label']} return-code drift："
                + ", ".join(left_replay["returncode_drift_instances"])
                + "。"
            )
        if right_replay.get("returncode_drift_instances"):
            lines.append(
                f"> {right_summary['label']} return-code drift："
                + ", ".join(right_replay["returncode_drift_instances"])
                + "。"
            )
    lines.extend(
        [
            "",
            "## Case 对比",
            "",
            "| Case | 左侧 actions | 右侧 actions | 差值 | 左侧退出 | 右侧退出 | patch 相同 |",
            "|---|---:|---:|---:|---|---|---|",
        ]
    )
    lines.extend(
        f"| {case['instance_id']} | {case['left_actions']} | {case['right_actions']} | "
        f"{case['action_delta']:+d} | {case['left_exit']} | {case['right_exit']} | "
        f"{'是' if case['same_patch'] else '否'} |"
        for case in paired
    )
    (output_dir / "comparison.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"output_dir": str(output_dir), "left": left_summary, "right": right_summary}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
