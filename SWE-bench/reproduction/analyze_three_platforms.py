#!/usr/bin/env python3
"""Compare paired SWE Golden lifecycle results across three servers."""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from pathlib import Path


MODES = ("k1", "k16")
PLATFORMS = ("agent", "zuchongzhi", "shenkuo")
PAIRS = (
    ("agent", "zuchongzhi"),
    ("agent", "shenkuo"),
    ("zuchongzhi", "shenkuo"),
)
METRICS = (
    "service_e2e_seconds",
    "sandbox_e2e_seconds",
    "tool_wall_seconds",
    "container_start_seconds",
    "agent_control_gap_seconds",
    "result_capture_seconds",
    "container_teardown_seconds",
)
METRIC_NAMES = {
    "service_e2e_seconds": "Service E2E",
    "sandbox_e2e_seconds": "Sandbox E2E",
    "tool_wall_seconds": "ToolCall",
    "container_start_seconds": "Container start",
    "agent_control_gap_seconds": "Agent control gap",
    "result_capture_seconds": "Result capture",
    "container_teardown_seconds": "Container teardown",
}
PLATFORM_NAMES = {
    "agent": "agent (Intel 8558P)",
    "zuchongzhi": "zuchongzhi (Hygon 7490)",
    "shenkuo": "shenkuo (Hygon 7480)",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--agent-run", type=Path, required=True)
    parser.add_argument("--zuchongzhi-run", type=Path, required=True)
    parser.add_argument("--shenkuo-run", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def case_map(summary: dict) -> dict[str, dict]:
    return {case["instance_id"]: case for case in summary["cases"]}


def geomean(values: list[float]) -> float:
    if not values or any(value <= 0 for value in values):
        raise ValueError("geomean requires positive values")
    return math.exp(statistics.fmean(math.log(value) for value in values))


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    rank = (len(ordered) - 1) * fraction
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (rank - lower)


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def fmt(value: float, digits: int = 3) -> str:
    return f"{value:.{digits}f}"


def ratio_text(value: float) -> str:
    return f"{value:.3f} ({(value - 1) * 100:+.1f}%)"


def main() -> None:
    args = parse_args()
    runs = {
        "agent": args.agent_run.resolve(),
        "zuchongzhi": args.zuchongzhi_run.resolve(),
        "shenkuo": args.shenkuo_run.resolve(),
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)

    summaries = {
        platform: {
            mode: load_json(run / mode / "performance_summary.json")
            for mode in MODES
        }
        for platform, run in runs.items()
    }
    case_maps = {
        (platform, mode): case_map(summaries[platform][mode])
        for platform in PLATFORMS
        for mode in MODES
    }
    expected = set(case_maps[("agent", "k1")])
    if len(expected) != 30:
        raise SystemExit(f"expected 30 cases, found {len(expected)}")
    for key, cases in case_maps.items():
        if set(cases) != expected:
            raise SystemExit(f"case set mismatch for {key}")
    for mode in MODES:
        for instance_id in expected:
            step_counts = {
                case_maps[(platform, mode)][instance_id]["step_count"]
                for platform in PLATFORMS
            }
            if len(step_counts) != 1:
                raise SystemExit(f"step count mismatch: {mode} {instance_id}")

    absolute_rows: list[dict] = []
    pair_rows: list[dict] = []
    stage_rows: list[dict] = []
    batch_rows: list[dict] = []
    scaling_rows: list[dict] = []
    analysis: dict = {
        "format_version": 1,
        "runs": {key: str(value) for key, value in runs.items()},
        "modes": {},
        "scaling": {},
    }

    for mode in MODES:
        mode_data: dict = {"pairs": {}}
        for platform in PLATFORMS:
            summary = summaries[platform][mode]
            batch_rows.append(
                {
                    "mode": mode,
                    "platform": platform,
                    "makespan_seconds": summary["elapsed_seconds"],
                    "throughput_cases_per_second": summary[
                        "throughput_cases_per_second"
                    ],
                    "cpu_utilization_mean_percent": summary[
                        "cpu_utilization_mean_percent"
                    ],
                    "semantic_passes": sum(
                        bool(case["semantic_pass"]) for case in summary["cases"]
                    ),
                }
            )
            for instance_id in sorted(expected):
                case = case_maps[(platform, mode)][instance_id]
                row = {
                    "mode": mode,
                    "platform": platform,
                    "instance_id": instance_id,
                    "project": instance_id.split("__", 1)[0],
                    "step_count": case["step_count"],
                    "semantic_pass": case["semantic_pass"],
                }
                row.update({metric: float(case[metric]) for metric in METRICS})
                absolute_rows.append(row)

        for baseline, candidate in PAIRS:
            pair_name = f"{candidate}_over_{baseline}"
            pair_data: dict = {}
            for instance_id in sorted(expected):
                baseline_case = case_maps[(baseline, mode)][instance_id]
                candidate_case = case_maps[(candidate, mode)][instance_id]
                row = {
                    "mode": mode,
                    "baseline": baseline,
                    "candidate": candidate,
                    "instance_id": instance_id,
                    "step_count": baseline_case["step_count"],
                }
                for metric in METRICS:
                    row[f"ratio_{metric}"] = (
                        float(candidate_case[metric]) / float(baseline_case[metric])
                    )
                pair_rows.append(row)

            for metric in METRICS:
                baseline_values = [
                    float(case_maps[(baseline, mode)][case][metric])
                    for case in sorted(expected)
                ]
                candidate_values = [
                    float(case_maps[(candidate, mode)][case][metric])
                    for case in sorted(expected)
                ]
                ratios = [
                    candidate_value / baseline_value
                    for baseline_value, candidate_value in zip(
                        baseline_values, candidate_values
                    )
                ]
                stage = {
                    "mode": mode,
                    "baseline": baseline,
                    "candidate": candidate,
                    "metric": metric,
                    "case_count": len(ratios),
                    "baseline_mean_seconds": statistics.fmean(baseline_values),
                    "candidate_mean_seconds": statistics.fmean(candidate_values),
                    "ratio_geomean": geomean(ratios),
                    "ratio_median": statistics.median(ratios),
                    "ratio_p90": percentile(ratios, 0.90),
                    "candidate_faster_cases": sum(value < 1 for value in ratios),
                    "candidate_slower_cases": sum(value > 1 for value in ratios),
                }
                stage_rows.append(stage)
                pair_data[metric] = stage
            mode_data["pairs"][pair_name] = pair_data
        analysis["modes"][mode] = mode_data

    for platform in PLATFORMS:
        platform_scaling: dict = {}
        for metric in ("service_e2e_seconds", "sandbox_e2e_seconds", "tool_wall_seconds"):
            ratios = [
                float(case_maps[(platform, "k16")][case][metric])
                / float(case_maps[(platform, "k1")][case][metric])
                for case in sorted(expected)
            ]
            value = geomean(ratios)
            platform_scaling[metric] = value
            scaling_rows.append(
                {
                    "platform": platform,
                    "metric": metric,
                    "k16_over_k1_geomean": value,
                }
            )
        throughput_ratio = (
            summaries[platform]["k16"]["throughput_cases_per_second"]
            / summaries[platform]["k1"]["throughput_cases_per_second"]
        )
        platform_scaling["throughput_k16_over_k1"] = throughput_ratio
        scaling_rows.append(
            {
                "platform": platform,
                "metric": "throughput_cases_per_second",
                "k16_over_k1_geomean": throughput_ratio,
            }
        )
        analysis["scaling"][platform] = platform_scaling

    analysis["validation"] = {
        "case_count": len(expected),
        "step_count_match": True,
        "semantic_passes": {
            platform: {
                mode: sum(
                    bool(case["semantic_pass"])
                    for case in summaries[platform][mode]["cases"]
                )
                for mode in MODES
            }
            for platform in PLATFORMS
        },
    }

    write_csv(args.output_dir / "three_platform_absolute_cases.csv", absolute_rows)
    write_csv(args.output_dir / "three_platform_paired_cases.csv", pair_rows)
    write_csv(args.output_dir / "three_platform_stage_metrics.csv", stage_rows)
    write_csv(args.output_dir / "three_platform_batch_summary.csv", batch_rows)
    write_csv(args.output_dir / "three_platform_scaling.csv", scaling_rows)
    with (args.output_dir / "three_platform_summary.json").open(
        "w", encoding="utf-8"
    ) as stream:
        json.dump(analysis, stream, ensure_ascii=False, indent=2)
        stream.write("\n")

    stage_index = {
        (row["mode"], row["baseline"], row["candidate"], row["metric"]): row
        for row in stage_rows
    }
    batch_index = {(row["mode"], row["platform"]): row for row in batch_rows}
    lines = [
        "# SWE Agent Golden Replay 三平台横向性能对比",
        "",
        "## 测试口径",
        "",
        "- 三个平台回放同一组 30 条 Flash Golden trajectory，step 数逐 case 一致。",
        "- `delay_scale=0`，不包含 LLM/API 等待；Agent 与 Sandbox 均限制在 CPU0-7。",
        "- 容器网络关闭，memory limit 为 16 GiB，PIDs limit 为 4096。",
        "- K=1 与 K=16 各一次；成对时延比为 `candidate / baseline`，小于 1 表示 candidate 更快。",
        "",
        "## 平台",
        "",
        "| 平台 | CPU | 拓扑 | 镜像布局 |",
        "|---|---|---|---|",
        "| agent | Intel Xeon Platinum 8558P | 2S, 48C/S, SMT2 | 原始多层 |",
        "| zuchongzhi | Hygon C86-4G OPN 7490 | 4S, 32C/S, SMT2 | 单层 flat-rootfs |",
        "| shenkuo | Hygon C86-4G OPN 7480 | 4S, 32C/S, SMT2 | 单层 flat-rootfs |",
        "",
        "## 批量吞吐",
        "",
        "| 模式 | 平台 | Makespan (s) | Throughput (case/s) | CPU0-7 平均利用率 | Semantic pass |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for mode in MODES:
        for platform in PLATFORMS:
            row = batch_index[(mode, platform)]
            lines.append(
                f"| {mode.upper()} | {PLATFORM_NAMES[platform]} | "
                f"{fmt(float(row['makespan_seconds']))} | "
                f"{fmt(float(row['throughput_cases_per_second']), 4)} | "
                f"{fmt(float(row['cpu_utilization_mean_percent']), 1)}% | "
                f"{row['semantic_passes']}/30 |"
            )

    lines.extend(
        [
            "",
            "## 成对阶段对比",
            "",
            "| 模式 | Candidate / Baseline | Service E2E | ToolCall | Container start | Candidate ToolCall 更快 case |",
            "|---|---|---:|---:|---:|---:|",
        ]
    )
    for mode in MODES:
        for baseline, candidate in PAIRS:
            service = stage_index[(mode, baseline, candidate, "service_e2e_seconds")]
            tool = stage_index[(mode, baseline, candidate, "tool_wall_seconds")]
            start = stage_index[(mode, baseline, candidate, "container_start_seconds")]
            lines.append(
                f"| {mode.upper()} | {candidate} / {baseline} | "
                f"{ratio_text(service['ratio_geomean'])} | "
                f"{ratio_text(tool['ratio_geomean'])} | "
                f"{ratio_text(start['ratio_geomean'])} | "
                f"{tool['candidate_faster_cases']}/30 |"
            )

    lines.extend(
        [
            "",
            "## Hygon 直接对比",
            "",
            "`shenkuo / zuchongzhi` 使用完全相同的单层 flat-rootfs，是本轮最干净的平台对比。",
            "",
            "| 模式 | 阶段 | Shenkuo 均值 (s) | Zuchongzhi 均值 (s) | Shenkuo / Zuchongzhi 几何均值 |",
            "|---|---|---:|---:|---:|",
        ]
    )
    for mode in MODES:
        for metric in METRICS:
            row = stage_index[(mode, "zuchongzhi", "shenkuo", metric)]
            lines.append(
                f"| {mode.upper()} | {METRIC_NAMES[metric]} | "
                f"{fmt(row['candidate_mean_seconds'])} | "
                f"{fmt(row['baseline_mean_seconds'])} | "
                f"{ratio_text(row['ratio_geomean'])} |"
            )

    lines.extend(
        [
            "",
            "## K16 扩展性",
            "",
            "| 平台 | K16/K1 ToolCall 时延 | K16/K1 Service E2E | K16/K1 吞吐 |",
            "|---|---:|---:|---:|",
        ]
    )
    for platform in PLATFORMS:
        scaling = analysis["scaling"][platform]
        lines.append(
            f"| {PLATFORM_NAMES[platform]} | "
            f"{fmt(scaling['tool_wall_seconds'])}x | "
            f"{fmt(scaling['service_e2e_seconds'])}x | "
            f"{fmt(scaling['throughput_k16_over_k1'])}x |"
        )

    lines.extend(
        [
            "",
            "## 解读边界",
            "",
            "- agent 使用原始多层镜像，而两个 Hygon 平台使用内容等价的单层 flat-rootfs；agent 的 container start/storage 差异不能全部归因于 CPU。",
            "- K=1 反映单 case 响应能力；K=16 同时包含核内竞争、调度和并发 Docker ToolCall 的扩展能力。",
            "- 本结果不含网络与 LLM 等待，不能代替在线 Agent 的用户端到端时延。",
            "",
        ]
    )
    (args.output_dir / "三平台横向性能对比.md").write_text(
        "\n".join(lines), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
