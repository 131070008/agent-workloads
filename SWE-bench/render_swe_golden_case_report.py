#!/usr/bin/env python3
"""Render a complete paired 30-case Golden latency report."""

from __future__ import annotations

import argparse
import csv
import html
import json
from pathlib import Path
from typing import Any

from replay_swe_trajectory import command_category


STAGES = (
    ("queue_wait_seconds", "Queue wait"),
    ("service_e2e_seconds", "Service E2E"),
    ("arrival_e2e_seconds", "Arrival E2E"),
    ("replay_process_overhead_seconds", "Replay process overhead"),
    ("process_instance_seconds", "Process instance"),
    ("startup_to_first_action_seconds", "Startup to first action"),
    ("agent_control_gap_seconds", "Agent control gap"),
    ("tool_wall_seconds", "Tool execution"),
    ("finish_tail_seconds", "Finish / cleanup tail"),
)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def fmt(value: float | None, digits: int = 3) -> str:
    return "-" if value is None else f"{value:.{digits}f}"


def load_cases(run_dir: Path) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    summary = read_json(run_dir / "performance_summary.json")
    cases: dict[str, dict[str, Any]] = {}
    for record in summary["cases"]:
        instance_id = record["instance_id"]
        timeline = read_json(Path(record["output_dir"]) / "step_timeline.json")
        cases[instance_id] = {"record": record, "timeline": timeline}
    return summary, cases


def write_stage_tsv(
    path: Path,
    instance_ids: list[str],
    baseline_label: str,
    primary_label: str,
    baseline: dict[str, dict[str, Any]],
    primary: dict[str, dict[str, Any]],
) -> None:
    columns = ["instance_id", "steps", "service_slowdown"]
    for key, _ in STAGES:
        columns.extend((f"{baseline_label}_{key}", f"{primary_label}_{key}"))
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, delimiter="\t")
        writer.writeheader()
        for instance_id in instance_ids:
            left = baseline[instance_id]["record"]
            right = primary[instance_id]["record"]
            row: dict[str, Any] = {
                "instance_id": instance_id,
                "steps": left["step_count"],
                "service_slowdown": right["service_e2e_seconds"] / left["service_e2e_seconds"],
            }
            for key, _ in STAGES:
                row[f"{baseline_label}_{key}"] = left[key]
                row[f"{primary_label}_{key}"] = right[key]
            writer.writerow(row)


def tool_rows(
    instance_ids: list[str],
    labels_and_cases: tuple[tuple[str, dict[str, dict[str, Any]]], ...],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for instance_id in instance_ids:
        for label, cases in labels_and_cases:
            for step in cases[instance_id]["timeline"].get("steps") or []:
                commands = step.get("commands") or []
                rows.append(
                    {
                        "instance_id": instance_id,
                        "concurrency": label,
                        "step": step.get("step"),
                        "category": command_category(commands),
                        "action_gap_seconds": step.get("action_gap_seconds"),
                        "tool_wall_seconds": step.get("tool_wall_seconds"),
                        "returncode": step.get("returncode"),
                        "output_chars": step.get("output_chars"),
                        "output_lines": step.get("output_lines"),
                        "command": " ; ".join(commands).replace("\n", "\\n"),
                    }
                )
    return rows


def write_tool_tsv(path: Path, rows: list[dict[str, Any]]) -> None:
    columns = (
        "instance_id",
        "concurrency",
        "step",
        "category",
        "action_gap_seconds",
        "tool_wall_seconds",
        "returncode",
        "output_chars",
        "output_lines",
        "command",
    )
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def stage_rows(left: dict[str, Any], right: dict[str, Any]) -> str:
    rows = []
    for key, label in STAGES:
        left_value = float(left[key])
        right_value = float(right[key])
        ratio = right_value / left_value if left_value else None
        rows.append(
            "<tr>"
            f"<th>{html.escape(label)}</th>"
            f"<td>{fmt(left_value)}</td><td>{fmt(right_value)}</td>"
            f"<td>{fmt(ratio, 2)}x</td>"
            "</tr>"
        )
    return "".join(rows)


def paired_tool_rows(left: dict[str, Any], right: dict[str, Any]) -> str:
    left_steps = left.get("steps") or []
    right_steps = right.get("steps") or []
    rows = []
    for index in range(max(len(left_steps), len(right_steps))):
        a = left_steps[index] if index < len(left_steps) else {}
        b = right_steps[index] if index < len(right_steps) else {}
        commands = a.get("commands") or b.get("commands") or []
        command = " ; ".join(commands)
        a_wall = a.get("tool_wall_seconds")
        b_wall = b.get("tool_wall_seconds")
        ratio = b_wall / a_wall if isinstance(a_wall, (int, float)) and a_wall else None
        category = command_category(commands)
        rows.append(
            "<tr>"
            f"<td>{index + 1}</td><td><span class='category'>{html.escape(category)}</span></td>"
            f"<td class='command'>{html.escape(command)}</td>"
            f"<td>{fmt(a.get('action_gap_seconds'))}</td><td>{fmt(b.get('action_gap_seconds'))}</td>"
            f"<td>{fmt(a_wall)}</td><td>{fmt(b_wall)}</td><td>{fmt(ratio, 2)}x</td>"
            f"<td>{html.escape(str(a.get('returncode', '-')))}</td>"
            f"<td>{html.escape(str(b.get('returncode', '-')))}</td>"
            "</tr>"
        )
    return "".join(rows)


def render_html(
    output: Path,
    instance_ids: list[str],
    baseline_label: str,
    primary_label: str,
    baseline_summary: dict[str, Any],
    primary_summary: dict[str, Any],
    baseline: dict[str, dict[str, Any]],
    primary: dict[str, dict[str, Any]],
) -> None:
    overview = []
    details = []
    for index, instance_id in enumerate(instance_ids, 1):
        left = baseline[instance_id]["record"]
        right = primary[instance_id]["record"]
        ratio = right["service_e2e_seconds"] / left["service_e2e_seconds"]
        anchor = f"case-{index}"
        overview.append(
            f"<tr data-case='{html.escape(instance_id.lower())}'>"
            f"<td><a href='#{anchor}'>{html.escape(instance_id)}</a></td>"
            f"<td>{left['step_count']}</td>"
            f"<td>{fmt(left['service_e2e_seconds'])}</td>"
            f"<td>{fmt(right['queue_wait_seconds'])}</td>"
            f"<td>{fmt(right['service_e2e_seconds'])}</td>"
            f"<td>{fmt(right['arrival_e2e_seconds'])}</td>"
            f"<td>{fmt(ratio, 2)}x</td>"
            f"<td>{fmt(left['tool_wall_seconds'])}</td>"
            f"<td>{fmt(right['tool_wall_seconds'])}</td>"
            "</tr>"
        )
        details.append(
            f"<details id='{anchor}'><summary><span>{index:02d}</span> {html.escape(instance_id)}"
            f"<strong>{fmt(left['service_e2e_seconds'])}s → {fmt(right['service_e2e_seconds'])}s</strong>"
            "</summary>"
            "<div class='case-body'>"
            "<h3>阶段时延（秒）</h3>"
            "<table><thead><tr><th>阶段</th>"
            f"<th>{html.escape(baseline_label)}</th><th>{html.escape(primary_label)}</th><th>Ratio</th>"
            f"</tr></thead><tbody>{stage_rows(left, right)}</tbody></table>"
            "<h3>逐 Tool Call 时延（秒）</h3>"
            "<div class='table-scroll'><table class='tools'><thead><tr>"
            "<th>#</th><th>类型</th><th>命令</th>"
            f"<th>{html.escape(baseline_label)} gap</th><th>{html.escape(primary_label)} gap</th>"
            f"<th>{html.escape(baseline_label)} tool</th><th>{html.escape(primary_label)} tool</th>"
            "<th>Ratio</th>"
            f"<th>{html.escape(baseline_label)} rc</th><th>{html.escape(primary_label)} rc</th>"
            f"</tr></thead><tbody>{paired_tool_rows(baseline[instance_id]['timeline'], primary[instance_id]['timeline'])}</tbody></table></div>"
            "</div></details>"
        )

    css = """
    :root { color-scheme: light; --ink:#202124; --muted:#687076; --line:#d9dddf; --accent:#0b6e4f; --warm:#b45309; --soft:#f5f7f6; }
    * { box-sizing:border-box; } body { margin:0; color:var(--ink); background:#fff; font:14px/1.5 Arial,"PingFang SC",sans-serif; }
    header { padding:28px 36px 20px; border-bottom:3px solid var(--accent); } h1 { margin:0 0 8px; font-size:28px; letter-spacing:0; }
    header p { margin:4px 0; color:var(--muted); } main { padding:24px 36px 60px; max-width:1600px; margin:auto; }
    .metrics { display:flex; gap:24px; flex-wrap:wrap; margin:20px 0; padding:14px 0; border-block:1px solid var(--line); }
    .metric b { display:block; font-size:21px; color:var(--accent); } .metric span { color:var(--muted); }
    input { width:min(460px,100%); padding:9px 11px; border:1px solid #aab1b4; border-radius:4px; margin:8px 0 14px; }
    table { width:100%; border-collapse:collapse; } th,td { padding:7px 9px; border-bottom:1px solid var(--line); text-align:right; vertical-align:top; }
    th { background:var(--soft); font-weight:600; position:sticky; top:0; z-index:1; } th:first-child,td:first-child,.command { text-align:left; }
    a { color:var(--accent); } details { border:1px solid var(--line); border-radius:6px; margin:12px 0; scroll-margin-top:12px; }
    summary { cursor:pointer; padding:12px 14px; font-size:16px; font-weight:600; display:flex; gap:10px; align-items:center; }
    summary span { color:var(--warm); } summary strong { margin-left:auto; font-size:14px; color:var(--accent); }
    .case-body { padding:0 14px 18px; } h2 { margin-top:30px; } h3 { margin:20px 0 8px; font-size:15px; }
    .table-scroll { overflow:auto; max-height:620px; border:1px solid var(--line); } .tools { min-width:1200px; }
    .tools .command { max-width:650px; white-space:pre-wrap; word-break:break-word; font:12px/1.4 ui-monospace,SFMono-Regular,Menlo,monospace; }
    .category { display:inline-block; border:1px solid #9eb4aa; color:var(--accent); padding:1px 5px; border-radius:3px; }
    .note { border-left:3px solid var(--warm); padding:8px 12px; background:#fffaf2; }
    @media (max-width:800px) { header,main { padding-inline:16px; } .overview-wrap { overflow:auto; } .overview { min-width:1000px; } }
    """
    baseline_tp = baseline_summary["throughput_cases_per_second"]
    primary_tp = primary_summary["throughput_cases_per_second"]
    document = f"""<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
    <title>SWE Golden 30 Case Latency Report</title><style>{css}</style></head><body>
    <header><h1>SWE Golden 30 Case 时延结果</h1>
    <p>固定 30 条 Flash Golden trajectory，CPU 0-7，delay_scale=0，逐 case 对比 {html.escape(baseline_label)} 与 {html.escape(primary_label)}。</p>
    <p>Arrival E2E = Queue wait + Service E2E；Service E2E = Replay process overhead + Process instance。</p></header>
    <main><div class='metrics'>
      <div class='metric'><b>30</b><span>完全配对 Cases</span></div>
      <div class='metric'><b>{baseline_tp:.4f}</b><span>{html.escape(baseline_label)} case/s</span></div>
      <div class='metric'><b>{primary_tp:.4f}</b><span>{html.escape(primary_label)} case/s</span></div>
      <div class='metric'><b>{primary_tp / baseline_tp:.2f}x</b><span>批次吞吐提升</span></div>
    </div>
    <p class='note'>{html.escape(baseline_label)} 的 service E2E 是单任务执行基线；表中的 arrival E2E 采用 30 条任务同时提交的批次到达口径。</p>
    <h2>30 Case 总览</h2><input id='filter' placeholder='筛选 instance_id'>
    <div class='overview-wrap'><table class='overview'><thead><tr><th>Instance ID</th><th>Steps</th><th>{html.escape(baseline_label)} Service</th>
    <th>{html.escape(primary_label)} Queue</th><th>{html.escape(primary_label)} Service</th><th>{html.escape(primary_label)} Arrival</th><th>Service Ratio</th>
    <th>{html.escape(baseline_label)} Tool</th><th>{html.escape(primary_label)} Tool</th></tr></thead><tbody>{''.join(overview)}</tbody></table></div>
    <h2>逐 Case 阶段与 Tool Call</h2>{''.join(details)}</main>
    <script>const f=document.getElementById('filter'); f.addEventListener('input',()=>{{const q=f.value.toLowerCase();document.querySelectorAll('.overview tbody tr').forEach(r=>r.hidden=!r.dataset.case.includes(q));}});</script>
    </body></html>"""
    output.write_text(document, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-run", type=Path, required=True)
    parser.add_argument("--primary-run", type=Path, required=True)
    parser.add_argument("--baseline-label", default="K=1")
    parser.add_argument("--primary-label", default="K=16")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    baseline_summary, baseline = load_cases(args.baseline_run.resolve())
    primary_summary, primary = load_cases(args.primary_run.resolve())
    if set(baseline) != set(primary):
        raise SystemExit("baseline and primary case sets differ")
    instance_ids = sorted(baseline)

    write_stage_tsv(
        args.output_dir / "all_30_cases_stage_latency.tsv",
        instance_ids,
        args.baseline_label,
        args.primary_label,
        baseline,
        primary,
    )
    rows = tool_rows(
        instance_ids,
        ((args.baseline_label, baseline), (args.primary_label, primary)),
    )
    write_tool_tsv(args.output_dir / "all_toolcalls_latency.tsv", rows)
    render_html(
        args.output_dir / "SWE_Golden_30_Case_Latency_Report.html",
        instance_ids,
        args.baseline_label,
        args.primary_label,
        baseline_summary,
        primary_summary,
        baseline,
        primary,
    )
    print(
        json.dumps(
            {
                "output_dir": str(args.output_dir),
                "cases": len(instance_ids),
                "toolcall_rows": len(rows),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
