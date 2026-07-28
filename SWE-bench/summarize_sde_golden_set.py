#!/usr/bin/env python3
"""Summarize a complete multi-case SWE Golden Intel SDE run."""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from summarize_sde_mix import build_summary


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def metrics(summary: dict[str, Any]) -> dict[str, Any]:
    classes = summary["classes"]
    return {
        "dynamic_instructions": summary["dynamic_instructions"],
        "branch_percent": classes["branch_instructions"]["percent_of_instructions"],
        "integer_alu_approx_percent": classes["integer_alu_approximation"]["percent_of_instructions"],
        "simd_family_approx_percent": classes["simd_family_approximation"]["percent_of_instructions"],
        "memory_read_operands_per_ki": classes["memory_read_operands"]["accesses_per_ki"],
        "memory_write_operands_per_ki": classes["memory_write_operands"]["accesses_per_ki"],
        "fp_elements_per_ki": classes["floating_point_elements"]["elements_per_ki"],
        "integer_vector_elements_per_ki": classes["integer_vector_elements"]["elements_per_ki"],
        "top_xed_categories": summary["top_xed_categories"],
    }


def summarize_paths(paths: list[Path]) -> dict[str, Any] | None:
    if not paths:
        return None
    summary = build_summary(paths)
    if not summary["dynamic_instructions"]:
        return None
    return metrics(summary)


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def metric_row(name: str, item: dict[str, Any] | None) -> str:
    if not item:
        return f"| {name} | 0 | - | - | - | - |"
    return (
        f"| {name} | {item['dynamic_instructions']:,} | "
        f"{item['branch_percent']:.3f}% | "
        f"{item['integer_alu_approx_percent']:.3f}% | "
        f"{item['memory_read_operands_per_ki']:.3f} | "
        f"{item['memory_write_operands_per_ki']:.3f} |"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    run_dir = args.run_dir.expanduser().resolve()

    all_paths: list[Path] = []
    label_paths: dict[str, list[Path]] = defaultdict(list)
    category_paths: dict[str, list[Path]] = defaultdict(list)
    case_paths: dict[tuple[str, str], list[Path]] = defaultdict(list)
    action_rows: list[dict[str, Any]] = []
    case_completions = sorted(run_dir.glob("cases/*/*/complete.json"))

    for complete_path in case_completions:
        complete = read_json(complete_path)
        label = complete["label"]
        instance_id = complete["instance_id"]
        attempt_dir = Path(complete["attempt_dir"])
        for metadata_path in sorted((attempt_dir / "sde_mix").glob("action_*/action_metadata.json")):
            metadata = read_json(metadata_path)
            mix_paths = sorted(metadata_path.parent.glob("mix*.txt"))
            action_summary = summarize_paths(mix_paths)
            row = {
                "label": label,
                "instance_id": instance_id,
                "action_index": metadata["action_index"],
                "category": metadata["category"],
                "returncode": metadata.get("returncode"),
                "elapsed_seconds": metadata.get("elapsed_seconds"),
                "command": metadata.get("command", "").replace("\n", "\\n"),
                "mix_file_count": len(mix_paths),
                "has_dynamic_mix": bool(action_summary),
            }
            if action_summary:
                row.update(action_summary)
                all_paths.extend(mix_paths)
                label_paths[label].extend(mix_paths)
                category_paths[metadata["category"]].extend(mix_paths)
                case_paths[(label, instance_id)].extend(mix_paths)
            action_rows.append(row)

    overall = summarize_paths(all_paths)
    by_label = {label: summarize_paths(paths) for label, paths in sorted(label_paths.items())}
    by_category = {
        category: summarize_paths(paths) for category, paths in sorted(category_paths.items())
    }
    case_rows: list[dict[str, Any]] = []
    for complete_path in case_completions:
        complete = read_json(complete_path)
        key = (complete["label"], complete["instance_id"])
        item = summarize_paths(case_paths.get(key, []))
        case_rows.append(
            {
                "label": key[0],
                "instance_id": key[1],
                "expected_action_count": complete["expected_action_count"],
                "instrumented_action_count": complete["instrumented_action_count"],
                "elapsed_seconds": complete["elapsed_seconds"],
                **(item or {}),
            }
        )

    output = {
        "format_version": 1,
        "run_dir": str(run_dir),
        "case_count": len(case_completions),
        "action_count": len(action_rows),
        "actions_with_dynamic_mix": sum(bool(row["has_dynamic_mix"]) for row in action_rows),
        "overall": overall,
        "by_label": by_label,
        "by_category": by_category,
        "cases": case_rows,
    }
    write_json(run_dir / "sde_golden_summary.json", output)
    action_fields = [
        "label",
        "instance_id",
        "action_index",
        "category",
        "returncode",
        "elapsed_seconds",
        "mix_file_count",
        "has_dynamic_mix",
        "dynamic_instructions",
        "branch_percent",
        "integer_alu_approx_percent",
        "simd_family_approx_percent",
        "memory_read_operands_per_ki",
        "memory_write_operands_per_ki",
        "fp_elements_per_ki",
        "integer_vector_elements_per_ki",
        "command",
    ]
    case_fields = [
        "label",
        "instance_id",
        "expected_action_count",
        "instrumented_action_count",
        "elapsed_seconds",
        "dynamic_instructions",
        "branch_percent",
        "integer_alu_approx_percent",
        "simd_family_approx_percent",
        "memory_read_operands_per_ki",
        "memory_write_operands_per_ki",
        "fp_elements_per_ki",
        "integer_vector_elements_per_ki",
    ]
    write_csv(run_dir / "sde_action_mix.csv", action_rows, action_fields)
    write_csv(run_dir / "sde_case_mix.csv", case_rows, case_fields)

    lines = [
        "# SWE Golden 全量 SDE 动态指令分布",
        "",
        f"- 完成 case：`{len(case_completions)}`",
        f"- ToolCall action：`{len(action_rows)}`",
        f"- 有有效动态指令的 action：`{output['actions_with_dynamic_mix']}`",
        "- 汇总方式：先合并动态计数器再计算比例，即按动态指令数加权，不是 case 百分比的算术平均。",
        "",
        "## 总体与模型",
        "",
        "| 范围 | 动态指令 | Branch | Integer ALU 近似 | Memory read / KI | Memory write / KI |",
        "|---|---:|---:|---:|---:|---:|",
        metric_row("combined", overall),
    ]
    lines.extend(metric_row(label, item) for label, item in by_label.items())
    lines.extend(
        [
            "",
            "## ToolCall 类型",
            "",
            "| 类型 | 动态指令 | Branch | Integer ALU 近似 | Memory read / KI | Memory write / KI |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    lines.extend(metric_row(category, item) for category, item in by_category.items())
    lines.extend(
        [
            "",
            "## 口径",
            "",
            "- 每条 trajectory 在一个独立、干净的 SWE 容器中按原 ToolCall 顺序重放，保持 case 内文件状态。",
            "- Intel SDE 动态插桩改变执行时延，因此本结果只用于 instruction mix，不用于性能对比。",
            "- Memory read/write 是动态内存操作数次数，不是 load/store 指令数。",
            "- Integer ALU 与 SIMD-family 是 XED category 近似；精确数据类型仍需更细的 iform 映射。",
            "",
        ]
    )
    (run_dir / "sde_golden_summary.md").write_text("\n".join(lines), encoding="utf-8")
    print(run_dir / "sde_golden_summary.md")


if __name__ == "__main__":
    main()
