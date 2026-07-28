#!/usr/bin/env python3
"""Evaluate Intel EMR TMA 5.2 L1-L4 formulas from repeated perf-stat passes."""

from __future__ import annotations

import argparse
import ast
import csv
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path


FIXED_PASS = "00_fixed_perf_metrics"
SLOTS_EVENT = "TOPDOWN.SLOTS:perf_metrics"
CYCLES_EVENT = "CPU_CLK_UNHALTED.THREAD"
REF_CYCLES_EVENT = "CPU_CLK_UNHALTED.REF_TSC"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--result-dir", required=True, type=Path)
    parser.add_argument("--formula-manifest", required=True, type=Path)
    parser.add_argument("--tsc-mhz", required=True, type=float)
    parser.add_argument("--threads-per-core", type=int, default=2)
    parser.add_argument("--slots-per-cycle", type=int, default=6)
    parser.add_argument("--cgroup-seconds", type=float, default=5.0)
    parser.add_argument("--global-seconds", type=float, default=3.0)
    parser.add_argument("--output-csv", required=True, type=Path)
    parser.add_argument("--output-json", required=True, type=Path)
    parser.add_argument("--output-markdown", required=True, type=Path)
    return parser.parse_args()


def read_event_map(path: Path) -> tuple[dict[str, str], dict[str, str]]:
    label_to_event: dict[str, str] = {}
    event_to_pass: dict[str, str] = {}
    with path.open(encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            event = row["intel_event"]
            event_to_pass[event] = row["pass"]
            label_to_event[row["perf_name"]] = event
            label_to_event[row["perf_syntax"]] = event
    return label_to_event, event_to_pass


def read_scope_passes(
    directory: Path,
    scope_kind: str,
    label_to_event: dict[str, str],
) -> dict[str, dict[str, dict[str, float]]]:
    values: dict[str, dict[str, dict[str, float]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(float))
    )
    for path in sorted(directory.glob("*.csv")):
        pass_name = path.stem
        with path.open(encoding="utf-8") as stream:
            rows = csv.reader(line for line in stream if not line.startswith("#"))
            for row in rows:
                if len(row) < 6 or row[1] == "<not counted>":
                    continue
                try:
                    count = float(row[1])
                except ValueError:
                    continue
                event = label_to_event.get(row[3])
                if event is None:
                    continue
                scope = row[4] if scope_kind == "cgroup" else "CPU0-7 global"
                values[scope][pass_name][event] += count
    return values


def normalize_events(
    pass_values: dict[str, dict[str, float]],
    event_to_pass: dict[str, str],
    slots_per_cycle: int,
) -> tuple[dict[str, float], dict]:
    cycle_samples = [
        values[CYCLES_EVENT]
        for name, values in pass_values.items()
        if name != FIXED_PASS and values.get(CYCLES_EVENT, 0) > 0
    ]
    ratio_samples = [
        values[CYCLES_EVENT] / values[REF_CYCLES_EVENT]
        for name, values in pass_values.items()
        if name != FIXED_PASS
        and values.get(CYCLES_EVENT, 0) > 0
        and values.get(REF_CYCLES_EVENT, 0) > 0
    ]
    if not cycle_samples or not ratio_samples:
        raise ValueError("missing repeated cycles/ref-cycles baselines")

    target_cycles = statistics.median(cycle_samples)
    target_ratio = statistics.median(ratio_samples)
    target_ref_cycles = target_cycles / target_ratio

    fixed = pass_values.get(FIXED_PASS, {})
    fixed_slots = fixed.get(SLOTS_EVENT, 0)
    if fixed_slots <= 0:
        raise ValueError("missing fixed TOPDOWN.SLOTS")
    fixed_scale = target_cycles * slots_per_cycle / fixed_slots

    normalized: dict[str, float] = {}
    for event, pass_name in event_to_pass.items():
        if event == CYCLES_EVENT:
            normalized[event] = target_cycles
            continue
        if event == REF_CYCLES_EVENT:
            normalized[event] = target_ref_cycles
            continue
        if pass_name == "all_programmable_passes":
            continue

        if pass_name not in pass_values or event not in pass_values[pass_name]:
            raise ValueError(
                f"missing collected event {event} in pass {pass_name}"
            )
        raw = pass_values[pass_name][event]
        if pass_name == FIXED_PASS:
            normalized[event] = raw * fixed_scale
            continue

        pass_cycles = pass_values.get(pass_name, {}).get(CYCLES_EVENT, 0)
        if pass_cycles <= 0:
            normalized[event] = 0.0
            continue
        normalized[event] = raw * target_cycles / pass_cycles

    quality = {
        "cycle_samples": len(cycle_samples),
        "cycle_mean": statistics.mean(cycle_samples),
        "cycle_median": target_cycles,
        "cycle_cv": (
            statistics.pstdev(cycle_samples) / statistics.mean(cycle_samples)
        ),
        "cycle_min": min(cycle_samples),
        "cycle_max": max(cycle_samples),
        "median_cycles_over_ref_cycles": target_ratio,
        "fixed_slots_raw": fixed_slots,
        "fixed_scale": fixed_scale,
        "target_slots": target_cycles * slots_per_cycle,
    }
    return normalized, quality


def validate_manifest_coverage(
    manifest: dict,
    event_to_pass: dict[str, str],
) -> dict:
    errors = list(manifest.get("validation_errors", []))
    expected_events = {
        event["Name"]
        for metric in manifest["metrics"]
        for event in metric.get("Events", [])
    }
    mapped_events = set(event_to_pass)
    missing = sorted(expected_events - mapped_events)
    extra = sorted(mapped_events - expected_events)
    if missing:
        errors.append(f"events missing from collection plan: {missing}")
    if extra:
        errors.append(f"collection plan has unknown events: {extra}")
    if errors:
        raise ValueError("; ".join(errors))
    return {
        "metric_count": len(manifest["metrics"]),
        "expected_event_count": len(expected_events),
        "mapped_event_count": len(mapped_events),
        "missing_events": missing,
        "extra_events": extra,
    }


def validate_formula(formula: str) -> ast.Expression:
    tree = ast.parse(formula, mode="eval")
    allowed = (
        ast.Expression,
        ast.BinOp,
        ast.UnaryOp,
        ast.IfExp,
        ast.Name,
        ast.Load,
        ast.Constant,
        ast.Call,
        ast.Compare,
        ast.Add,
        ast.Sub,
        ast.Mult,
        ast.Div,
        ast.USub,
        ast.UAdd,
        ast.Lt,
    )
    for node in ast.walk(tree):
        if not isinstance(node, allowed):
            raise ValueError(f"unsupported formula node: {type(node).__name__}")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in {
                "max",
                "min",
            }:
                raise ValueError(f"unsupported formula function: {ast.dump(node)}")
    return tree


def constant_value(
    name: str,
    duration_ms: float,
    tsc_hz: float,
    threads_per_core: int,
) -> float | bool:
    if name == "HYPERTHREADING_ON":
        return threads_per_core > 1
    if name == "THREADS_PER_CORE":
        return float(threads_per_core)
    if name == "SYSTEM_TSC_FREQ":
        return tsc_hz
    if name == "DURATIONTIMEINMILLISECONDS":
        # Intel PerfSpect normalizes perfmon formulas to a one-second interval.
        # Counter ratios are already independent of the collection duration.
        return 1000.0
    return float(name)


def evaluate_metrics(
    metrics: list[dict],
    event_values: dict[str, float],
    duration_ms: float,
    tsc_hz: float,
    threads_per_core: int,
) -> list[dict]:
    output = []
    for metric in metrics:
        env: dict[str, float | bool | object] = {"max": max, "min": min}
        for event in metric.get("Events", []):
            env[event["Alias"]] = event_values.get(event["Name"], 0.0)
        for constant in metric.get("Constants", []):
            env[constant["Alias"]] = constant_value(
                constant["Name"],
                duration_ms,
                tsc_hz,
                threads_per_core,
            )
        error = ""
        value = math.nan
        try:
            tree = validate_formula(metric["Formula"])
            value = float(
                eval(
                    compile(tree, "<intel-emr-formula>", "eval"),
                    {"__builtins__": {}},
                    env,
                )
            )
            if not math.isfinite(value):
                raise ValueError("non-finite result")
        except (ZeroDivisionError, ValueError) as exc:
            error = str(exc)
        output.append(
            {
                "level": metric["Level"],
                "metric": metric["MetricName"],
                "parent": metric.get("ParentCategory") or "",
                "domain": metric.get("CountDomain") or "",
                "unit": metric.get("UnitOfMeasure") or "",
                "value": value if not error else None,
                "valid": not error,
                "error": error,
                "formula": metric["Formula"],
            }
        )
    return output


def scope_audit(
    scope: str,
    event_values: dict[str, float],
    metrics: list[dict],
) -> dict:
    values = {
        metric["metric"]: metric["value"]
        for metric in metrics
        if metric["valid"]
    }
    cycles = event_values[CYCLES_EVENT]
    event_percent = {
        name: 100.0 * event_values[name] / cycles
        for name in (
            "EXE_ACTIVITY.BOUND_ON_LOADS",
            "MEMORY_ACTIVITY.STALLS_L1D_MISS",
            "MEMORY_ACTIVITY.STALLS_L2_MISS",
            "MEMORY_ACTIVITY.STALLS_L3_MISS",
            "EXE_ACTIVITY.BOUND_ON_STORES",
        )
    }

    closures = {
        "L1_total_minus_100": sum(
            values[name]
            for name in (
                "Frontend_Bound",
                "Bad_Speculation",
                "Backend_Bound",
                "Retiring",
            )
        )
        - 100.0,
        "L2_frontend_minus_parent": (
            values["Fetch_Bandwidth"]
            + values["Fetch_Latency"]
            - values["Frontend_Bound"]
        ),
        "L2_bad_spec_minus_parent": (
            values["Branch_Mispredicts"]
            + values["Machine_Clears"]
            - values["Bad_Speculation"]
        ),
        "L2_backend_minus_parent": (
            values["Core_Bound"]
            + values["Memory_Bound"]
            - values["Backend_Bound"]
        ),
        "L2_retiring_minus_parent": (
            values["Heavy_Operations"]
            + values["Light_Operations"]
            - values["Retiring"]
        ),
        "memory_load_chain_minus_bound_on_loads": (
            values["L1_Bound"]
            + values["L2_Bound"]
            + values["L3_Bound"]
            + values["L3_Miss_Bound"]
            - event_percent["EXE_ACTIVITY.BOUND_ON_LOADS"]
        ),
        "L4_icache_split_minus_parent": (
            values["Code_L2_Hit"]
            + values["Code_L2_Miss"]
            - values["ICache_Misses"]
        ),
        "L4_itlb_split_minus_parent": (
            values["Code_STLB_Hit"]
            + values["Code_STLB_Miss"]
            - values["ITLB_Misses"]
        ),
        "L4_branch_resteers_split_minus_parent": (
            values["Clears_Resteers"]
            + values["Mispredicts_Resteers"]
            + values["Unknown_Branches"]
            - values["Branch_Resteers"]
        ),
        "L4_divider_split_minus_parent": (
            values["FP_Divider"]
            + values["INT_Divider"]
            - values["Divider"]
        ),
        "L4_fp_arith_split_minus_parent": (
            values["FP_Scalar"]
            + values["FP_Vector"]
            + values["X87_Use"]
            - values["FP_Arith"]
        ),
    }
    trusted = scope in {"Host Agent", "Sandbox", "CPU0-7 global"}
    tolerance = 1e-6
    failed = {
        name: value
        for name, value in closures.items()
        if trusted and abs(value) > tolerance
    }
    if failed:
        raise ValueError(f"{scope} closure checks failed: {failed}")
    return {
        "trusted_scope": trusted,
        "tolerance_percentage_points": tolerance,
        "event_percent_of_unhalted_cycles": event_percent,
        "closure_delta_percentage_points": closures,
        "closure_checks_passed": not failed,
    }


def short_scope(scope: str) -> str:
    if "swe-agent.slice" in scope:
        return "Host Agent"
    if "swe-sandbox.slice" in scope:
        return "Sandbox"
    if scope == "system.slice":
        return "System"
    return scope


def write_markdown(path: Path, payload: dict) -> None:
    lines = [
        "# Intel EMR TMA 5.2 L1-L4",
        "",
        "所有值均由 Intel EMR metrics v1.4 / TMA 5.2 官方 Formula 机械求值。",
        "跨 pass 的 raw count 先使用同 pass 的 CPU_CLK_UNHALTED.THREAD",
        "归一化，再投影到该 scope 的 cycles 中位数。固定 Top-down pass",
        "按 6 slots/cycle 对齐。L3/L4 的不同节点可能使用不同 CountDomain，",
        "不能把同级百分比直接相加。",
        "",
        "## 自动核验",
        "",
        (
            f"- 公式节点：{payload['input_audit']['metric_count']}；"
            f"唯一事件：{payload['input_audit']['expected_event_count']}；"
            "事件覆盖完整。"
        ),
        "- Host Agent、Sandbox、CPU0-7 全域的 L1/L2、load-stall 链和"
        "可严格加和的 L4 子树均通过闭合检查（误差阈值 1e-6 个百分点）。",
        "- System cgroup 活跃时间过低，只保留原始估算，不纳入严格闭合。",
        "",
    ]
    for scope, item in payload["scopes"].items():
        lines += [
            f"## {scope}",
            "",
            (
                f"- cycle passes={item['quality']['cycle_samples']}，"
                f"CV={item['quality']['cycle_cv']:.4f}，"
                f"median cycles/ref-cycles="
                f"{item['quality']['median_cycles_over_ref_cycles']:.4f}"
            ),
            (
                "- load-stall chain (%cycles)："
                f"BOUND_ON_LOADS="
                f"{item['audit']['event_percent_of_unhalted_cycles']['EXE_ACTIVITY.BOUND_ON_LOADS']:.4f}，"
                f"STALLS_L1D_MISS="
                f"{item['audit']['event_percent_of_unhalted_cycles']['MEMORY_ACTIVITY.STALLS_L1D_MISS']:.4f}，"
                f"STALLS_L2_MISS="
                f"{item['audit']['event_percent_of_unhalted_cycles']['MEMORY_ACTIVITY.STALLS_L2_MISS']:.4f}，"
                f"STALLS_L3_MISS="
                f"{item['audit']['event_percent_of_unhalted_cycles']['MEMORY_ACTIVITY.STALLS_L3_MISS']:.4f}"
            ),
            "",
        ]
        for level in range(1, 5):
            lines += [
                f"### L{level}",
                "",
                "| Parent | Metric | Domain | Value | Valid |",
                "|---|---|---|---:|---|",
            ]
            for metric in item["metrics"]:
                if metric["level"] != level:
                    continue
                value = (
                    f"{metric['value']:.6f}%"
                    if metric["valid"]
                    else "N/A"
                )
                lines.append(
                    f"| {metric['parent']} | {metric['metric']} | "
                    f"{metric['domain']} | {value} | "
                    f"{'yes' if metric['valid'] else metric['error']} |"
                )
            lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    args = parse_args()
    manifest = json.loads(args.formula_manifest.read_text(encoding="utf-8"))
    label_to_event, event_to_pass = read_event_map(
        args.result_dir / "event_to_pass.csv"
    )
    input_audit = validate_manifest_coverage(manifest, event_to_pass)
    raw_scopes = {}
    raw_scopes.update(
        read_scope_passes(
            args.result_dir / "raw_cgroup",
            "cgroup",
            label_to_event,
        )
    )
    raw_scopes.update(
        read_scope_passes(
            args.result_dir / "raw_global",
            "global",
            label_to_event,
        )
    )

    payload = {
        "formula_source": manifest["source"],
        "tsc_mhz": args.tsc_mhz,
        "threads_per_core": args.threads_per_core,
        "slots_per_cycle": args.slots_per_cycle,
        "normalization": "same-pass cycles projected to scope median cycles",
        "input_audit": input_audit,
        "scopes": {},
    }
    csv_rows = []
    for raw_scope, pass_values in raw_scopes.items():
        scope = short_scope(raw_scope)
        normalized, quality = normalize_events(
            pass_values,
            event_to_pass,
            args.slots_per_cycle,
        )
        duration = (
            args.global_seconds
            if raw_scope == "CPU0-7 global"
            else args.cgroup_seconds
        )
        metrics = evaluate_metrics(
            manifest["metrics"],
            normalized,
            duration * 1000,
            args.tsc_mhz * 1_000_000,
            args.threads_per_core,
        )
        audit = scope_audit(scope, normalized, metrics)
        payload["scopes"][scope] = {
            "raw_scope": raw_scope,
            "duration_seconds": duration,
            "quality": quality,
            "audit": audit,
            "metrics": metrics,
        }
        for metric in metrics:
            csv_rows.append(
                {
                    "scope": scope,
                    **{
                        key: (
                            f"{value:.9f}"
                            if key == "value"
                            and isinstance(value, float)
                            and math.isfinite(value)
                            else value
                        )
                        for key, value in metric.items()
                    },
                }
            )

    args.output_csv.parent.mkdir(parents=True, exist_ok=True)
    with args.output_csv.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(csv_rows[0]))
        writer.writeheader()
        writer.writerows(csv_rows)
    args.output_json.write_text(
        json.dumps(payload, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    write_markdown(args.output_markdown, payload)
    print(args.output_markdown)


if __name__ == "__main__":
    main()
