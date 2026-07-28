#!/usr/bin/env python3
"""Summarize Intel SDE mix output into workload-oriented instruction classes."""

from __future__ import annotations

import argparse
import glob
import json
import re
from collections import Counter
from pathlib import Path
from typing import Iterable


MIX_LINE = re.compile(r"^\*(\S+)\s+(\d+)\s*$")
BRANCH_CATEGORIES = ("CALL", "COND_BR", "RET", "UNCOND_BR")
INTEGER_ALU_CATEGORIES = (
    "BINARY",
    "BITBYTE",
    "BMI1",
    "BMI2",
    "CMOV",
    "LOGICAL",
    "ROTATE",
    "SETCC",
    "SHIFT",
)
SIMD_FAMILY_CATEGORIES = (
    "AVX",
    "AVX2",
    "AVX512",
    "BROADCAST",
    "KMASK",
    "LOGICAL_FP",
    "SSE",
)


def expand_inputs(patterns: Iterable[str]) -> list[Path]:
    paths: set[Path] = set()
    for pattern in patterns:
        matches = glob.glob(pattern, recursive=True)
        if matches:
            paths.update(Path(match).resolve() for match in matches)
        elif Path(pattern).exists():
            paths.add(Path(pattern).resolve())
    return sorted(path for path in paths if not path.is_dir())


def read_global_mix(path: Path) -> Counter[str]:
    values: Counter[str] = Counter()
    in_global = False
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("# EMIT_GLOBAL_DYNAMIC_STATS"):
            in_global = True
            continue
        if in_global and line.startswith("# END_GLOBAL_DYNAMIC_STATS"):
            break
        if not in_global:
            continue
        match = MIX_LINE.match(line)
        if match:
            values[match.group(1)] += int(match.group(2))
    return values


def category_sum(values: Counter[str], names: Iterable[str]) -> int:
    return sum(values[f"category-{name}"] for name in names)


def ratio(value: int, total: int) -> float:
    return 100.0 * value / total if total else 0.0


def per_ki(value: int, total: int) -> float:
    return 1000.0 * value / total if total else 0.0


def build_summary(paths: list[Path]) -> dict:
    aggregate: Counter[str] = Counter()
    used: list[str] = []
    skipped: list[str] = []
    for path in paths:
        values = read_global_mix(path)
        if values["total"] <= 0:
            skipped.append(str(path))
            continue
        aggregate.update(values)
        used.append(str(path))

    total = aggregate["total"]
    categories = {
        key.removeprefix("category-"): value
        for key, value in aggregate.items()
        if key.startswith("category-")
    }
    branch = category_sum(aggregate, BRANCH_CATEGORIES)
    integer_alu = category_sum(aggregate, INTEGER_ALU_CATEGORIES)
    simd_family = category_sum(aggregate, SIMD_FAMILY_CATEGORIES)
    fp_elements = sum(
        value for key, value in aggregate.items() if key.startswith("elements_fp_")
    )
    integer_vector_elements = sum(
        value for key, value in aggregate.items() if key.startswith("elements_i")
    )
    memory_reads = aggregate["mem-read"]
    memory_writes = aggregate["mem-write"]

    return {
        "format_version": 1,
        "input_files": used,
        "skipped_files_without_global_mix": skipped,
        "dynamic_instructions": total,
        "classes": {
            "branch_instructions": {
                "count": branch,
                "percent_of_instructions": ratio(branch, total),
                "categories": list(BRANCH_CATEGORIES),
            },
            "integer_alu_approximation": {
                "count": integer_alu,
                "percent_of_instructions": ratio(integer_alu, total),
                "categories": list(INTEGER_ALU_CATEGORIES),
            },
            "simd_family_approximation": {
                "count": simd_family,
                "percent_of_instructions": ratio(simd_family, total),
                "categories": list(SIMD_FAMILY_CATEGORIES),
            },
            "memory_read_operands": {
                "count": memory_reads,
                "accesses_per_ki": per_ki(memory_reads, total),
            },
            "memory_write_operands": {
                "count": memory_writes,
                "accesses_per_ki": per_ki(memory_writes, total),
            },
            "floating_point_elements": {
                "count": fp_elements,
                "elements_per_ki": per_ki(fp_elements, total),
            },
            "integer_vector_elements": {
                "count": integer_vector_elements,
                "elements_per_ki": per_ki(integer_vector_elements, total),
            },
        },
        "top_xed_categories": sorted(
            categories.items(), key=lambda item: (-item[1], item[0])
        )[:20],
        "raw_dynamic_counters": dict(sorted(aggregate.items())),
        "interpretation_limits": [
            "Memory read/write values count dynamic memory operands, not load/store instructions.",
            "SSE/AVX XED categories contain mixed data types; SIMD-family is not an exact FP count.",
            "elements_fp_* counts floating-point lane operations; it is not an instruction count.",
            "Scalar integer work is only approximated by selected XED categories.",
        ],
    }


def render_markdown(summary: dict) -> str:
    classes = summary["classes"]
    total = summary["dynamic_instructions"]
    lines = [
        "# Intel SDE 动态指令分布",
        "",
        f"- 有效进程输出：`{len(summary['input_files'])}`",
        f"- 动态指令总数：`{total:,}`",
        "",
        "| 指标 | 数量 | 归一化结果 |",
        "|---|---:|---:|",
    ]
    for label, key, result_key in (
        ("Branch（CALL/RET/条件/无条件跳转）", "branch_instructions", "percent_of_instructions"),
        ("Integer ALU 近似", "integer_alu_approximation", "percent_of_instructions"),
        ("SIMD family 近似", "simd_family_approximation", "percent_of_instructions"),
        ("Memory read operands", "memory_read_operands", "accesses_per_ki"),
        ("Memory write operands", "memory_write_operands", "accesses_per_ki"),
        ("FP elements", "floating_point_elements", "elements_per_ki"),
        ("Integer vector elements", "integer_vector_elements", "elements_per_ki"),
    ):
        item = classes[key]
        suffix = "%" if result_key == "percent_of_instructions" else "/KI"
        lines.append(
            f"| {label} | {item['count']:,} | {item[result_key]:.3f}{suffix} |"
        )
    lines.extend(
        [
            "",
            "## Top XED Categories",
            "",
            "| Category | Count | Instructions Share |",
            "|---|---:|---:|",
        ]
    )
    for category, count in summary["top_xed_categories"]:
        lines.append(f"| {category} | {count:,} | {ratio(count, total):.3f}% |")
    lines.extend(
        [
            "",
            "## 口径限制",
            "",
            "- Memory read/write 是动态内存操作数访问次数，不是 load/store 指令条数。",
            "- SSE/AVX category 可能混合整数、浮点与数据搬运，不能直接当作精确 FP 比例。",
            "- `elements_fp_*` 是浮点 lane operations，不是指令数。",
            "- 精确 INT/FP 指令分类需要继续按 XED iform/opcode 语义映射。",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", help="SDE mix files or glob patterns")
    parser.add_argument("--json", type=Path)
    parser.add_argument("--markdown", type=Path)
    args = parser.parse_args()

    paths = expand_inputs(args.inputs)
    if not paths:
        raise SystemExit("No SDE mix files found")
    summary = build_summary(paths)
    if not summary["dynamic_instructions"]:
        raise SystemExit("No global dynamic instruction counts found")

    payload = json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
    markdown = render_markdown(summary)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(payload, encoding="utf-8")
    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(markdown, encoding="utf-8")
    print(markdown)


if __name__ == "__main__":
    main()
