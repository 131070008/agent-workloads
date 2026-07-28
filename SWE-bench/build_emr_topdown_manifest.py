#!/usr/bin/env python3
"""Build an auditable EMR Top-down L1-L4 formula and event manifest."""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import re
from pathlib import Path


ROOT_METRICS = {
    "Frontend_Bound",
    "Bad_Speculation",
    "Backend_Bound",
    "Retiring",
}

SPECIAL_EVENTS = {
    "PERF_METRICS.FRONTEND_BOUND": "cpu/topdown-fe-bound/",
    "PERF_METRICS.BAD_SPECULATION": "cpu/topdown-bad-spec/",
    "PERF_METRICS.BACKEND_BOUND": "cpu/topdown-be-bound/",
    "PERF_METRICS.RETIRING": "cpu/topdown-retiring/",
    "PERF_METRICS.BRANCH_MISPREDICTS": "cpu/topdown-br-mispredict/",
    "PERF_METRICS.MEMORY_BOUND": "cpu/topdown-mem-bound/",
    "PERF_METRICS.HEAVY_OPERATIONS": "cpu/topdown-heavy-ops/",
    "PERF_METRICS.FETCH_LATENCY": "cpu/topdown-fetch-lat/",
    "TOPDOWN.SLOTS": "cpu/slots/",
    "CPU_CLK_UNHALTED.THREAD": "cycles",
    "CPU_CLK_UNHALTED.REF_TSC": "ref-cycles",
    "INST_RETIRED.ANY": "instructions",
}

ALLOWED_FORMULA_CALLS = {"max", "min"}
MODIFIER_RE = re.compile(r"^(?P<kind>[ce])(?P<value>\d+)$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--metrics-json", required=True, type=Path)
    parser.add_argument("--events-json", required=True, type=Path)
    parser.add_argument("--markdown", required=True, type=Path)
    parser.add_argument("--csv", required=True, type=Path)
    parser.add_argument("--manifest-json", required=True, type=Path)
    return parser.parse_args()


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_formula(metric: dict) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    formula = metric["Formula"]
    aliases = {
        item["Alias"]
        for item in metric.get("Events", []) + metric.get("Constants", [])
    }
    try:
        tree = ast.parse(formula, mode="eval")
    except SyntaxError as exc:
        return errors + [f"invalid formula syntax: {exc}"], warnings

    used_aliases = {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and node.id not in ALLOWED_FORMULA_CALLS
    }
    undeclared = used_aliases - aliases
    unused = aliases - used_aliases
    if undeclared:
        errors.append(
            f"formula uses undeclared aliases {sorted(undeclared)}"
        )
    if unused:
        warnings.append(f"declared but unused aliases {sorted(unused)}")

    allowed_nodes = (
        ast.Expression,
        ast.BinOp,
        ast.UnaryOp,
        ast.BoolOp,
        ast.Compare,
        ast.Call,
        ast.IfExp,
        ast.Name,
        ast.Load,
        ast.Constant,
        ast.Add,
        ast.Sub,
        ast.Mult,
        ast.Div,
        ast.BitAnd,
        ast.BitOr,
        ast.And,
        ast.Or,
        ast.USub,
        ast.UAdd,
        ast.Gt,
        ast.GtE,
        ast.Lt,
        ast.LtE,
        ast.Eq,
        ast.NotEq,
    )
    for node in ast.walk(tree):
        if not isinstance(node, allowed_nodes):
            errors.append(f"unsupported formula node: {type(node).__name__}")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in ALLOWED_FORMULA_CALLS:
                errors.append(f"unsupported formula call: {ast.dump(node.func)}")
    return errors, warnings


def split_event_name(name: str) -> tuple[str, list[str]]:
    fields = name.split(":")
    return fields[0], fields[1:]


def event_encoding(name: str, event_map: dict[str, dict]) -> dict:
    base, modifiers = split_event_name(name)
    if base in SPECIAL_EVENTS:
        counter = (
            "fixed PERF_METRICS"
            if base.startswith("PERF_METRICS.") or base == "TOPDOWN.SLOTS"
            else "architectural fixed"
        )
        return {
            "name": name,
            "base_name": base,
            "perf_syntax": SPECIAL_EVENTS[base],
            "counter": counter,
            "taken_alone": "0",
            "offcore": "0",
            "msr_index": "n/a",
            "msr_value": "n/a",
            "errata": "null",
            "speculative": "1",
        }

    event = event_map.get(base)
    if event is None:
        return {
            "name": name,
            "base_name": base,
            "error": "event not found in EMR core JSON",
        }

    cmask = int(event.get("CounterMask", "0"), 0)
    edge = int(event.get("EdgeDetect", "0"), 0)
    msr_value = event.get("MSRValue", "0x00")
    msr_override = None
    for modifier in modifiers:
        match = MODIFIER_RE.match(modifier)
        if match:
            value = int(match.group("value"))
            if match.group("kind") == "c":
                cmask = value
            else:
                edge = value
        elif modifier.startswith("ocr_msr_val="):
            msr_override = modifier.split("=", 1)[1]
        elif modifier != "perf_metrics":
            return {
                "name": name,
                "base_name": base,
                "error": f"unsupported event modifier: {modifier}",
            }

    code = event["EventCode"].split(",")[0].lower()
    umask = event["UMask"].lower()
    fields = [f"event={code}", f"umask={umask}"]
    if cmask:
        fields.append(f"cmask={cmask}")
    if edge:
        fields.append(f"edge={edge}")

    msr_index = event.get("MSRIndex", "0x00")
    if msr_index.lower() == "0x3f7":
        fields.append(f"frontend={msr_value.lower()}")
    elif event.get("Offcore") == "1":
        fields.append(f"offcore_rsp={msr_value.lower()}")
        if msr_override is not None:
            fields.append(f"config1={msr_override.lower()}")

    return {
        "name": name,
        "base_name": base,
        "perf_syntax": "cpu/" + ",".join(fields) + "/",
        "event_code": event["EventCode"],
        "umask": event["UMask"],
        "counter": event["Counter"],
        "taken_alone": event["TakenAlone"],
        "offcore": event["Offcore"],
        "msr_index": msr_index,
        "msr_value": msr_value,
        "msr_override": msr_override,
        "counter_mask": str(cmask),
        "edge_detect": str(edge),
        "errata": event.get("Errata", "null"),
        "precise": event.get("Precise", "0"),
        "speculative": event.get("Speculative", "0"),
    }


def selected_metrics(metrics: list[dict]) -> list[dict]:
    selected = []
    for metric in metrics:
        level = metric.get("Level")
        if metric.get("Category") != "TMA":
            continue
        if level == 1 and metric["MetricName"] in ROOT_METRICS:
            selected.append(metric)
        elif level in {2, 3, 4}:
            selected.append(metric)
    return sorted(selected, key=lambda item: (item["Level"], item["MetricName"]))


def esc(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def write_markdown(path: Path, manifest: dict) -> None:
    header = manifest["source"]["metrics_header"]
    metrics = manifest["metrics"]
    events = manifest["events"]
    lines = [
        "# Emerald Rapids Top-down L1-L4 公式与事件清单",
        "",
        "该文件由 Intel EMR 官方 metrics/event JSON 机械生成，不手抄公式。",
        "",
        "## 固定版本",
        "",
        f"- 平台：{header['Info']}",
        f"- TMA：{header['TmaVersion']} / {header['TmaFlavor']}",
        f"- Metrics：v{header['Version']}，{header['DatePublished']}",
        f"- Metrics SHA256：`{manifest['source']['metrics_sha256']}`",
        f"- Events SHA256：`{manifest['source']['events_sha256']}`",
        "",
        "## 公式",
        "",
        "| Level | Metric | Parent | Domain | Intel Formula | BaseFormula | Events | Constants |",
        "|---:|---|---|---|---|---|---|---|",
    ]
    for metric in metrics:
        event_text = ", ".join(
            f"{item['Alias']}={item['Name']}" for item in metric["Events"]
        )
        constant_text = ", ".join(
            f"{item['Alias']}={item['Name']}" for item in metric.get("Constants", [])
        )
        lines.append(
            "| {Level} | {MetricName} | {ParentCategory} | {CountDomain} | "
            "`{Formula}` | `{BaseFormula}` | {events} | {constants} |".format(
                **{
                    key: esc(value)
                    for key, value in {
                        "ParentCategory": "",
                        "CountDomain": "",
                        "BaseFormula": "",
                        **metric,
                    }.items()
                },
                events=esc(event_text),
                constants=esc(constant_text),
            )
        )

    lines += [
        "",
        "## 原始事件",
        "",
        "| Event | perf syntax | Counter | Alone | Offcore | MSR index/value | Errata |",
        "|---|---|---|---:|---:|---|---|",
    ]
    for event in events:
        if "error" in event:
            perf_syntax = f"ERROR: {event['error']}"
        else:
            perf_syntax = event["perf_syntax"]
        lines.append(
            f"| {esc(event['name'])} | `{esc(perf_syntax)}` | "
            f"{esc(event.get('counter', 'n/a'))} | "
            f"{esc(event.get('taken_alone', 'n/a'))} | "
            f"{esc(event.get('offcore', 'n/a'))} | "
            f"{esc(event.get('msr_index', 'n/a'))}/{esc(event.get('msr_value', 'n/a'))} | "
            f"{esc(event.get('errata', 'n/a'))} |"
        )

    lines += [
        "",
        "## 自动校验",
        "",
        f"- 指标数：{len(metrics)}",
        f"- 唯一事件数：{len(events)}",
        f"- 校验错误数：{len(manifest['validation_errors'])}",
        f"- 校验警告数：{len(manifest['validation_warnings'])}",
    ]
    if manifest["validation_errors"]:
        lines.extend(f"- ERROR: {esc(error)}" for error in manifest["validation_errors"])
    else:
        lines.append("- 结果：公式别名、父子层级和事件映射全部通过。")
    lines.extend(
        f"- WARNING: {esc(warning)}" for warning in manifest["validation_warnings"]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_csv(path: Path, metrics: list[dict]) -> None:
    fields = [
        "Level",
        "MetricName",
        "ParentCategory",
        "CountDomain",
        "UnitOfMeasure",
        "Formula",
        "BaseFormula",
        "Events",
        "Constants",
        "ResolutionLevels",
        "MetricGroup",
    ]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for metric in metrics:
            row = {field: metric.get(field, "") for field in fields}
            row["Events"] = ";".join(
                f"{item['Alias']}={item['Name']}" for item in metric["Events"]
            )
            row["Constants"] = ";".join(
                f"{item['Alias']}={item['Name']}"
                for item in metric.get("Constants", [])
            )
            writer.writerow(row)


def main() -> None:
    args = parse_args()
    metrics_data = load_json(args.metrics_json)
    events_data = load_json(args.events_json)
    metrics = selected_metrics(metrics_data["Metrics"])
    metric_by_name = {metric["MetricName"]: metric for metric in metrics}
    event_map = {event["EventName"]: event for event in events_data["Events"]}
    errors: list[str] = []
    warnings: list[str] = []

    for metric in metrics:
        name = metric["MetricName"]
        formula_errors, formula_warnings = validate_formula(metric)
        errors.extend(f"{name}: {error}" for error in formula_errors)
        warnings.extend(f"{name}: {warning}" for warning in formula_warnings)
        if metric["Level"] > 1:
            parent = metric.get("ParentCategory")
            if parent not in metric_by_name:
                errors.append(f"{name}: parent {parent} is missing")
            elif metric_by_name[parent]["Level"] != metric["Level"] - 1:
                errors.append(
                    f"{name}: parent level {metric_by_name[parent]['Level']} "
                    f"!= {metric['Level'] - 1}"
                )

    unique_event_names = sorted(
        {event["Name"] for metric in metrics for event in metric.get("Events", [])}
    )
    events = [event_encoding(name, event_map) for name in unique_event_names]
    errors.extend(
        f"{event['name']}: {event['error']}" for event in events if "error" in event
    )

    manifest = {
        "source": {
            "metrics_header": metrics_data["Header"],
            "events_header": events_data["Header"],
            "metrics_sha256": sha256(args.metrics_json),
            "events_sha256": sha256(args.events_json),
        },
        "metrics": metrics,
        "events": events,
        "validation_errors": errors,
        "validation_warnings": warnings,
    }

    for path in (args.markdown, args.csv, args.manifest_json):
        path.parent.mkdir(parents=True, exist_ok=True)
    write_markdown(args.markdown, manifest)
    write_csv(args.csv, metrics)
    args.manifest_json.write_text(
        json.dumps(manifest, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )

    print(
        f"metrics={len(metrics)} events={len(events)} "
        f"errors={len(errors)} warnings={len(warnings)} markdown={args.markdown}"
    )
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
