#!/usr/bin/env python3
import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


def parse_kv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    return values


def number(value: str) -> float | None:
    value = value.strip()
    if not value or value.startswith("<"):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def cgroup_label(path: str) -> str:
    if "swe-agent.slice" in path:
        return "host_agent"
    if "swe-sandbox.slice" in path:
        return "sandbox"
    normalized = path if path.startswith("/") else f"/{path}"
    if normalized == "/system.slice" or normalized.startswith("/system.slice/"):
        return "system_services"
    return path


def parse_cgroup_comm_report(path: Path) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    by_domain: dict[str, Counter[str]] = defaultdict(Counter)
    domain_totals: Counter[str] = Counter()
    row_pattern = re.compile(r"^\s*([0-9.]+)%\s+(\S+)\s+(.+?)\s*$")

    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = row_pattern.match(line)
        if not match:
            continue
        overhead = float(match.group(1))
        cgroup = match.group(2)
        comm = match.group(3).strip()
        domain = cgroup_label(cgroup)
        if domain not in {"host_agent", "sandbox", "system_services"}:
            domain = "other"
        rows.append(
            {
                "overhead_percent": overhead,
                "domain": domain,
                "cgroup": cgroup,
                "comm": comm,
            }
        )
        by_domain[domain][comm] += overhead
        domain_totals[domain] += overhead

    return {
        "domain_percent": dict(domain_totals),
        "comm_percent_by_domain": {
            domain: dict(counter.most_common()) for domain, counter in by_domain.items()
        },
        "rows": rows,
    }


def aggregate_perf_events(files: Iterable[Path]) -> dict[str, dict[str, float]]:
    totals: dict[tuple[str, str], float] = defaultdict(float)
    durations: dict[tuple[str, str], float] = defaultdict(float)

    for path in files:
        elapsed = 0.0
        seen: set[tuple[str, str]] = set()
        with path.open(newline="", encoding="utf-8") as stream:
            for row in csv.reader(stream):
                if len(row) < 6:
                    continue
                timestamp = number(row[0])
                value = number(row[2])
                event = row[4].strip()
                cgroup = cgroup_label(row[5].strip())
                if timestamp is None or value is None or not event or not cgroup:
                    continue
                elapsed = max(elapsed, timestamp)
                key = (cgroup, event)
                totals[key] += value
                seen.add(key)
        for key in seen:
            durations[key] += elapsed

    result: dict[str, dict[str, float]] = defaultdict(dict)
    for (cgroup, event), total in totals.items():
        duration = durations[(cgroup, event)]
        if duration > 0:
            result[cgroup][event] = total / duration
    return dict(result)


def aggregate_topdown(files: Iterable[Path]) -> dict[str, float]:
    sums: dict[str, float] = defaultdict(float)
    samples: Counter[str] = Counter()
    for path in files:
        with path.open(newline="", encoding="utf-8") as stream:
            reader = csv.reader(stream)
            header = [item.strip() for item in next(reader)]
            for row in reader:
                for index in range(2, min(len(header), len(row))):
                    value = number(row[index])
                    if value is None or not header[index]:
                        continue
                    sums[header[index]] += value
                    samples[header[index]] += 1
    return {name: sums[name] / samples[name] for name in sums}


def aggregate_ddr(path: Path) -> dict[str, dict[str, float]]:
    counts: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    duration: dict[str, float] = defaultdict(float)
    with path.open(newline="", encoding="utf-8") as stream:
        for row in csv.reader(stream):
            if len(row) < 6:
                continue
            timestamp = number(row[0])
            socket = row[1].strip()
            value = number(row[3])
            event = row[5].strip()
            if timestamp is None or value is None or not socket.startswith("S"):
                continue
            direction = "read" if "read" in event else "write" if "write" in event else ""
            if not direction:
                continue
            counts[socket][direction] += value
            duration[socket] = max(duration[socket], timestamp)

    result: dict[str, dict[str, float]] = {}
    for socket, directions in counts.items():
        seconds = duration[socket]
        read = directions["read"] * 64 / seconds / 1e9
        write = directions["write"] * 64 / seconds / 1e9
        result[socket] = {
            "read_gbps": read,
            "write_gbps": write,
            "total_gbps": read + write,
            "duration_seconds": seconds,
        }
    return result


def aggregate_network(path: Path) -> dict[str, dict[str, float]]:
    result: dict[str, dict[str, float]] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        fields = line.split()
        if len(fields) < 10 or fields[0] != "Average:":
            continue
        try:
            result[fields[1]] = {
                "rx_packets_per_second": float(fields[2]),
                "tx_packets_per_second": float(fields[3]),
                "rx_kib_per_second": float(fields[4]),
                "tx_kib_per_second": float(fields[5]),
            }
        except ValueError:
            continue
    return result


def aggregate_mpstat(path: Path, started_at: str, ended_at: str) -> dict[str, Any]:
    start = datetime.fromisoformat(started_at)
    end = datetime.fromisoformat(ended_at)
    values: dict[int, list[list[float]]] = defaultdict(list)

    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        fields = line.split()
        if len(fields) != 12 or not fields[1].isdigit():
            continue
        cpu = int(fields[1])
        if cpu > 7:
            continue
        try:
            timestamp = datetime.combine(start.date(), datetime.strptime(fields[0], "%H:%M:%S").time(), start.tzinfo)
            metrics = [float(item) for item in fields[2:12]]
        except ValueError:
            continue
        if start <= timestamp <= end:
            values[cpu].append(metrics)

    names = ["usr", "nice", "sys", "iowait", "irq", "soft", "steal", "guest", "gnice", "idle"]
    per_cpu: dict[str, dict[str, float]] = {}
    all_samples: list[list[float]] = []
    for cpu, samples in sorted(values.items()):
        all_samples.extend(samples)
        per_cpu[str(cpu)] = {
            name: sum(sample[index] for sample in samples) / len(samples)
            for index, name in enumerate(names)
        }
    aggregate = {
        name: sum(sample[index] for sample in all_samples) / len(all_samples)
        for index, name in enumerate(names)
    }
    return {"aggregate": aggregate, "per_cpu": per_cpu, "samples": len(all_samples)}


def walk_usage(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        usage = value.get("usage")
        if isinstance(usage, dict):
            yield usage
        for child in value.values():
            yield from walk_usage(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_usage(child)


def aggregate_trajectories(run_dir: Path) -> dict[str, Any]:
    totals: Counter[str] = Counter()
    cases: Counter[str] = Counter()
    models: Counter[str] = Counter()
    exit_statuses: Counter[str] = Counter()
    api_calls = 0
    usage_records = 0
    files = sorted(run_dir.glob("jobs/**/*.traj.json"))

    for path in files:
        data = json.loads(path.read_text(encoding="utf-8"))
        cases[str(data.get("instance_id", "unknown"))] += 1
        info = data.get("info", {})
        model_stats = info.get("model_stats", {})
        api_calls += int(model_stats.get("api_calls", 0) or 0)
        exit_statuses[str(info.get("exit_status", "unknown"))] += 1
        for usage in walk_usage(data):
            usage_records += 1
            totals["prompt_tokens"] += int(usage.get("prompt_tokens", 0) or 0)
            totals["completion_tokens"] += int(usage.get("completion_tokens", 0) or 0)
            totals["total_tokens"] += int(usage.get("total_tokens", 0) or 0)
            details = usage.get("prompt_tokens_details", {}) or {}
            totals["cached_tokens"] += int(details.get("cached_tokens", 0) or 0)

        for item in data.get("messages", []):
            if not isinstance(item, dict):
                continue
            extra = item.get("extra", {})
            response = extra.get("response", {}) if isinstance(extra, dict) else {}
            model = response.get("model") if isinstance(response, dict) else None
            if model:
                models[str(model)] += 1

    return {
        "trajectory_files": len(files),
        "api_calls": api_calls,
        "usage_records": usage_records,
        **dict(totals),
        "cases": dict(cases),
        "models": dict(models),
        "exit_statuses": dict(exit_statuses),
        "scope": "lower_bound_from_completed_trajectories",
    }


def parse_sched_latency(path: Path) -> dict[str, Any]:
    tasks: list[dict[str, Any]] = []
    total_runtime_ms = 0.0
    total_switches = 0
    lost_event_percent = 0.0
    task_pattern = re.compile(
        r"^\s*(.*?)\s+\|\s*([0-9.]+) ms\s*\|\s*([0-9]+)\s*\|"
        r"\s*avg:\s*([0-9.]+) ms\s*\|\s*max:\s*([0-9.]+) ms"
    )
    total_pattern = re.compile(r"TOTAL:.*?\|\s*([0-9.]+) ms\s*\|\s*([0-9]+)")
    lost_pattern = re.compile(r"INFO:\s*([0-9.]+)% lost events")

    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if match := task_pattern.match(line):
            tasks.append(
                {
                    "task": match.group(1).strip(),
                    "runtime_ms": float(match.group(2)),
                    "switches": int(match.group(3)),
                    "average_delay_ms": float(match.group(4)),
                    "max_delay_ms": float(match.group(5)),
                }
            )
        elif match := total_pattern.search(line):
            total_runtime_ms = float(match.group(1))
            total_switches = int(match.group(2))
        elif match := lost_pattern.search(line):
            lost_event_percent = float(match.group(1))
    return {
        "tasks": tasks,
        "total_runtime_ms": total_runtime_ms,
        "total_switches": total_switches,
        "lost_event_percent": lost_event_percent,
    }


def ratio(numerator: float, denominator: float) -> float:
    return 100.0 * numerator / denominator if denominator else 0.0


def per_ki(event_count: float, instructions: float) -> float:
    return 1000.0 * event_count / instructions if instructions else 0.0


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize a formal 96-agent SWE PMU run")
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()

    run_dir = args.run_dir.resolve()
    pmu_dir = run_dir / "perf_collect/formal/pmu"
    status = parse_kv(run_dir / "formal_status.txt")
    events: dict[str, dict[str, float]] = defaultdict(dict)
    events_by_group: dict[int, dict[str, dict[str, float]]] = {}
    for group in range(2, 10):
        values = aggregate_perf_events(sorted(pmu_dir.glob(f"round*_{group:02d}_*.csv")))
        events_by_group[group] = values
        for cgroup, event_values in values.items():
            # Preserve the baseline fixed-counter rates in the flat summary.
            # Later collectors repeat fixed counters in every raw-event pass.
            for event, value in event_values.items():
                if group != 2 and event in {"cycles", "instructions"}:
                    continue
                events[cgroup][event] = value

    topdown = aggregate_topdown(sorted(pmu_dir.glob("round*_01_topdown_l2.csv")))
    ddr = aggregate_ddr(pmu_dir / "ddr_imc.csv")
    network = aggregate_network(run_dir / "perf_collect/formal/network_sar.log")
    sched = parse_sched_latency(run_dir / "perf_collect/formal/perf_sched_latency_0_7.txt")
    cgroup_comm = parse_cgroup_comm_report(
        run_dir / "perf_collect/formal/perf_cgroup_comm_report.txt"
    )
    mpstat = aggregate_mpstat(
        run_dir / f"mpstat_{status.get('duration_seconds', '480')}s.log",
        status["ready_at"],
        status["collection_completed_at"],
    )
    tokens = aggregate_trajectories(run_dir)

    for cgroup, values in events.items():
        def group_denominator(group: int, event: str) -> float:
            return events_by_group.get(group, {}).get(cgroup, {}).get(
                event, values.get(event, 0.0)
            )

        values["ipc"] = values.get("instructions", 0.0) / values.get("cycles", 1.0)
        values["cpu_pool_percent"] = values.get("task-clock", 0.0) / 80.0
        values["branch_miss_percent"] = ratio(values.get("branch-misses", 0.0), values.get("branches", 0.0))
        values["l2_demand_miss_percent"] = ratio(values.get("l2_demand_data_read_miss", 0.0), values.get("l2_demand_data_read", 0.0))
        values["llc_miss_percent"] = ratio(values.get("llc_miss", 0.0), values.get("llc_reference", 0.0))
        values["mpki_same_pass"] = all(
            "instructions" in events_by_group.get(group, {}).get(cgroup, {})
            for group in range(3, 10)
        )
        values["branch_miss_mpki_estimate"] = per_ki(
            values.get("branch-misses", 0.0), group_denominator(2, "instructions")
        )
        values["l2_demand_miss_mpki_estimate"] = per_ki(
            values.get("l2_demand_data_read_miss", 0.0), group_denominator(5, "instructions")
        )
        values["retired_load_l3_miss_mpki_estimate"] = per_ki(
            values.get("mem_load_l3_miss", 0.0), group_denominator(3, "instructions")
        )
        values["llc_miss_event_per_ki_estimate"] = per_ki(
            values.get("llc_miss", 0.0), group_denominator(5, "instructions")
        )
        values["dtlb_load_walk_mpki_estimate"] = per_ki(
            values.get("dtlb_load_walk_completed", 0.0), group_denominator(6, "instructions")
        )
        values["dtlb_store_walk_mpki_estimate"] = per_ki(
            values.get("dtlb_store_walk_completed", 0.0), group_denominator(6, "instructions")
        )
        values["itlb_walk_mpki_estimate"] = per_ki(
            values.get("itlb_walk_completed", 0.0), group_denominator(7, "instructions")
        )
        # Legacy traces named raw event 0x80/0x04 "icache_iftag_miss". On
        # Emerald Rapids this event is ICACHE_DATA.STALLS, measured in cycles.
        icache_stall_cycles = values.get(
            "icache_data_stall_cycles", values.get("icache_iftag_miss", 0.0)
        )
        values["icache_data_stall_cycles"] = icache_stall_cycles
        values["icache_data_stall_cycles_per_ki_estimate"] = per_ki(
            icache_stall_cycles, group_denominator(7, "instructions")
        )
        values["icache_data_stall_cycles_percent"] = ratio(
            icache_stall_cycles, group_denominator(7, "cycles")
        )
        for event in ("mem_load_l1_hit", "mem_load_l2_hit", "mem_load_l3_hit"):
            values[f"{event}_per_ki_estimate"] = per_ki(
                values.get(event, 0.0), group_denominator(3, "instructions")
            )
        for event in ("l3_miss_local_dram", "l3_miss_remote_dram"):
            values[f"{event}_per_ki_estimate"] = per_ki(
                values.get(event, 0.0), group_denominator(4, "instructions")
            )
        for event, group in (
            ("dtlb_load_stlb_hit", 6),
            ("dtlb_store_stlb_hit", 6),
            ("itlb_stlb_hit", 7),
        ):
            values[f"{event}_per_ki_estimate"] = per_ki(
                values.get(event, 0.0), group_denominator(group, "instructions")
            )
        dram_reads = values.get("l3_miss_local_dram", 0.0) + values.get(
            "l3_miss_remote_dram", 0.0
        )
        values["remote_dram_share_percent"] = ratio(
            values.get("l3_miss_remote_dram", 0.0), dram_reads
        )
        stall_cycles = group_denominator(8, "cycles")
        for event in (
            "cycle_activity_stalls_total",
            "cycle_activity_stalls_l1d_miss",
            "cycle_activity_stalls_l2_miss",
            "cycle_activity_stalls_l3_miss",
        ):
            values[f"{event}_percent"] = ratio(values.get(event, 0.0), stall_cycles)

        prefetch_instructions = group_denominator(9, "instructions")
        demand_reads = values.get("ocr_demand_data_any", 0.0)
        hwpf_reads = values.get("ocr_hwpf_l1d_l2_any", 0.0)
        hwpf_misses = values.get("l2_hwpf_miss", 0.0)
        useless_hwpf = values.get("l2_useless_hwpf", 0.0)
        values["demand_data_read_per_ki"] = per_ki(demand_reads, prefetch_instructions)
        values["hwpf_l1d_l2_per_ki"] = per_ki(hwpf_reads, prefetch_instructions)
        values["hardware_prefetch_read_request_share_percent"] = ratio(
            hwpf_reads, demand_reads + hwpf_reads
        )
        values["l2_hwpf_miss_per_ki"] = per_ki(hwpf_misses, prefetch_instructions)
        values["l2_useless_hwpf_per_ki"] = per_ki(useless_hwpf, prefetch_instructions)
        values["l2_useless_per_hwpf_miss_percent_proxy"] = ratio(
            useless_hwpf, hwpf_misses
        )

    summary = {
        "run_dir": str(run_dir),
        "status": status,
        "topdown_percent": topdown,
        "cgroup_event_rate_per_second": events,
        "ddr": ddr,
        "network": network,
        "mpstat_collection_window": mpstat,
        "sched_latency_0_7": sched,
        "cgroup_comm_sample": cgroup_comm,
        "tokens": tokens,
    }
    (run_dir / "formal_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    agent = events.get("host_agent", {})
    sandbox = events.get("sandbox", {})
    system_services = events.get("system_services", {})
    mpki_note = (
        "各 raw-event pass 都携带同组 `instructions` 固定计数器，上表 MPKI 为严格同窗比值。"
        if agent.get("mpki_same_pass") and sandbox.get("mpki_same_pass")
        else "本轮 `instructions` 与 cache/TLB raw event 位于不同的 10 秒稳态 pass，所以上表 MPKI 是跨窗口均值估算，不是严格同窗比值。"
    )
    physical = network.get("ens16f0", {})
    total_cpu = (
        agent.get("cpu_pool_percent", 0.0)
        + sandbox.get("cpu_pool_percent", 0.0)
        + system_services.get("cpu_pool_percent", 0.0)
    )
    prefetch_collected = bool(events_by_group.get(9))
    prefetch_lines = []
    if prefetch_collected:
        prefetch_lines = [
            "",
            "### Demand 与 hardware prefetch",
            "",
            "| 指标 | host agent | sandbox |",
            "|---|---:|---:|",
            f"| demand data read / KI | {agent.get('demand_data_read_per_ki', 0):.3f} | {sandbox.get('demand_data_read_per_ki', 0):.3f} |",
            f"| L1D/L2 HW prefetch read / KI | {agent.get('hwpf_l1d_l2_per_ki', 0):.3f} | {sandbox.get('hwpf_l1d_l2_per_ki', 0):.3f} |",
            f"| HW prefetch offcore read-request 占比 | {agent.get('hardware_prefetch_read_request_share_percent', 0):.2f}% | {sandbox.get('hardware_prefetch_read_request_share_percent', 0):.2f}% |",
            f"| L2 HWPF true miss / KI | {agent.get('l2_hwpf_miss_per_ki', 0):.3f} | {sandbox.get('l2_hwpf_miss_per_ki', 0):.3f} |",
            f"| confirmed useless L2 HWPF / KI | {agent.get('l2_useless_hwpf_per_ki', 0):.3f} | {sandbox.get('l2_useless_hwpf_per_ki', 0):.3f} |",
            f"| useless / L2 HWPF miss（近似） | {agent.get('l2_useless_per_hwpf_miss_percent_proxy', 0):.2f}% | {sandbox.get('l2_useless_per_hwpf_miss_percent_proxy', 0):.2f}% |",
            "",
            "offcore read-request 占比的分母只包含 demand data read 与 core L1D/L2 hardware-prefetch read，二者在同一 PMU pass 统计；它是请求构成，不是 DDR 字节流量，且不包含 code fetch、software prefetch、RFO/write prefetch 和 L3-only prefetch。`L2 HWPF true miss` 表示请求访问到 L2 以下层级，不是 bad；只有 `L2_LINES_OUT.USELESS_HWPF` 明确表示该预取线在被 demand 使用前已驱逐。最后一行因 request 与 eviction 生命周期并不完全对齐，只作为浪费比例的近似。",
        ]
    sched_capacity_ms = float(status.get("sched_seconds", 30)) * 8 * 1000
    sched_rows = []
    for item in sched["tasks"][:8]:
        average_slice_us = (
            item["runtime_ms"] * 1000.0 / item["switches"] if item["switches"] else 0.0
        )
        sched_rows.append(
            f"| `{item['task']}` | {item['runtime_ms'] / 1000.0:.3f} s | "
            f"{item['runtime_ms'] / sched_capacity_ms * 100:.2f}% | "
            f"{item['switches'] / float(status.get('sched_seconds', 30)):.0f} | "
            f"{average_slice_us:.1f} us | "
            f"{item['average_delay_ms']:.3f} ms |"
        )
    comm_domain_rows = []
    for domain in ("host_agent", "sandbox", "system_services", "other"):
        share = cgroup_comm["domain_percent"].get(domain, 0.0)
        top = list(cgroup_comm["comm_percent_by_domain"].get(domain, {}).items())[:5]
        top_text = ", ".join(f"`{comm}` {percent:.2f}%" for comm, percent in top) or "-"
        comm_domain_rows.append(f"| {domain} | {share:.2f}% | {top_text} |")
    lines = [
        "# 96-agent SWE 正式 PMU 实验摘要",
        "",
        "## 实验状态",
        "",
        f"- 运行目录：`{run_dir}`",
        f"- 请求模型：`{status.get('requested_model')}`；API 实际模型：`{status.get('preflight_response_model')}`",
        f"- 稳态入口：{status.get('ready_active_jobs')} active jobs / {status.get('ready_containers')} containers",
        f"- PMU：{status.get('pmu_rounds')} 轮 x {status.get('pmu_passes_per_round', 'unknown')} 组，每组 {status.get('pass_seconds')} 秒；collector/sched/sar RC = {status.get('collector_rc')}/{status.get('sched_rc')}/{status.get('sar_rc')}",
        f"- launched/completed jobs：{status.get('launched_jobs')}/{status.get('completed_jobs')}；剩余容器：{status.get('remaining_minisweagent_containers')}",
        "",
        "## CPU 与 cgroup",
        "",
        "| 指标 | host agent | sandbox | system services |",
        "|---|---:|---:|---:|",
        f"| 8 核池 CPU 占用 | {agent.get('cpu_pool_percent', 0):.2f}% | {sandbox.get('cpu_pool_percent', 0):.2f}% | {system_services.get('cpu_pool_percent', 0):.2f}% |",
        f"| IPC | {agent.get('ipc', 0):.3f} | {sandbox.get('ipc', 0):.3f} | {system_services.get('ipc', 0):.3f} |",
        f"| branch miss | {agent.get('branch_miss_percent', 0):.3f}% | {sandbox.get('branch_miss_percent', 0):.3f}% | {system_services.get('branch_miss_percent', 0):.3f}% |",
        f"| context switch/s | {agent.get('context-switches', 0):.0f} | {sandbox.get('context-switches', 0):.0f} | {system_services.get('context-switches', 0):.0f} |",
        f"| CPU migration/s | {agent.get('cpu-migrations', 0):.0f} | {sandbox.get('cpu-migrations', 0):.0f} | {system_services.get('cpu-migrations', 0):.0f} |",
        f"| page fault/s | {agent.get('page-faults', 0):.0f} | {sandbox.get('page-faults', 0):.0f} | {system_services.get('page-faults', 0):.0f} |",
        *(
            [
                f"| minor fault/s | {agent.get('minor-faults', 0):.0f} | {sandbox.get('minor-faults', 0):.0f} | {system_services.get('minor-faults', 0):.0f} |",
                f"| major fault/s | {agent.get('major-faults', 0):.0f} | {sandbox.get('major-faults', 0):.0f} | {system_services.get('major-faults', 0):.0f} |",
            ]
            if any(
                "minor-faults" in values or "major-faults" in values
                for values in events.values()
            )
            else []
        ),
        "",
        f"三个显式 cgroup 在 8 核池合计占用约 **{total_cpu:.2f}%**；mpstat 平均 user/sys/idle = "
        f"**{mpstat['aggregate']['usr']:.2f}% / {mpstat['aggregate']['sys']:.2f}% / {mpstat['aggregate']['idle']:.2f}%**。",
        "",
        "### Cgroup x 进程类型（全域 99 Hz 样本）",
        "",
        "| 执行域 | 全部 CPU 样本占比 | 域内主要 comm（占全域样本） |",
        "|---|---:|---|",
        *comm_domain_rows,
        "",
        "该表由同一时间窗内的 `perf record --all-cgroups` 生成，可直接区分 host Python 与 sandbox Python。这里的“全域”是 CPU0-7 内不按目标 cgroup 过滤，不是整台 192-logical-CPU 服务器。`system_services` 是 `system.slice` 中落到 CPU0-7 的系统服务，不等同于纯 Docker 开销；若该项为 0，只能说明采样窗内这些服务没有在 CPU0-7 留下样本。未绑定的 `dockerd/containerd` 可能运行在池外 CPU，不能据此称其开销为零。",
        "",
        "## Top-down",
        "",
        "### Level 1",
        "",
        "| Retiring | Bad speculation | Frontend bound | Backend bound | Memory bound | Core bound |",
        "|---:|---:|---:|---:|---:|---:|",
        f"| {topdown.get('retiring', 0):.2f}% | {topdown.get('bad speculation', 0):.2f}% | {topdown.get('frontend bound', 0):.2f}% | {topdown.get('backend bound', 0):.2f}% | {topdown.get('memory bound', 0):.2f}% | {topdown.get('Core bound', 0):.2f}% |",
        "",
        "### Level 2",
        "",
        "| Level 1 | Level 2A | Level 2B |",
        "|---|---:|---:|",
        f"| Retiring | Heavy operations {topdown.get('heavy operations', 0):.2f}% | Light operations {topdown.get('light operations', 0):.2f}% |",
        f"| Bad speculation | Branch mispredict {topdown.get('branch mispredict', 0):.2f}% | Machine clears {topdown.get('machine clears', 0):.2f}% |",
        f"| Frontend bound | Fetch latency {topdown.get('fetch latency', 0):.2f}% | Fetch bandwidth {topdown.get('fetch bandwidth', 0):.2f}% |",
        f"| Backend bound | Memory bound {topdown.get('memory bound', 0):.2f}% | Core bound {topdown.get('Core bound', 0):.2f}% |",
        "",
        "## Cache、TLB 与内存",
        "",
        "| 指标 | host agent | sandbox |",
        "|---|---:|---:|",
        f"| Branch MPKI | {agent.get('branch_miss_mpki_estimate', 0):.3f} | {sandbox.get('branch_miss_mpki_estimate', 0):.3f} |",
        f"| L2 demand miss MPKI | {agent.get('l2_demand_miss_mpki_estimate', 0):.3f} | {sandbox.get('l2_demand_miss_mpki_estimate', 0):.3f} |",
        f"| retired load L3 miss MPKI | {agent.get('retired_load_l3_miss_mpki_estimate', 0):.3f} | {sandbox.get('retired_load_l3_miss_mpki_estimate', 0):.3f} |",
        f"| broad LLC miss event / KI | {agent.get('llc_miss_event_per_ki_estimate', 0):.3f} | {sandbox.get('llc_miss_event_per_ki_estimate', 0):.3f} |",
        f"| L2 demand miss | {agent.get('l2_demand_miss_percent', 0):.3f}% | {sandbox.get('l2_demand_miss_percent', 0):.3f}% |",
        f"| LLC miss/reference | {agent.get('llc_miss_percent', 0):.3f}% | {sandbox.get('llc_miss_percent', 0):.3f}% |",
        f"| DTLB load walk MPKI | {agent.get('dtlb_load_walk_mpki_estimate', 0):.3f} | {sandbox.get('dtlb_load_walk_mpki_estimate', 0):.3f} |",
        f"| DTLB store walk MPKI | {agent.get('dtlb_store_walk_mpki_estimate', 0):.3f} | {sandbox.get('dtlb_store_walk_mpki_estimate', 0):.3f} |",
        f"| ITLB walk MPKI | {agent.get('itlb_walk_mpki_estimate', 0):.3f} | {sandbox.get('itlb_walk_mpki_estimate', 0):.3f} |",
        f"| L1I-miss fetch-stall cycles / KI | {agent.get('icache_data_stall_cycles_per_ki_estimate', 0):.3f} | {sandbox.get('icache_data_stall_cycles_per_ki_estimate', 0):.3f} |",
        f"| L1I-miss fetch-stall cycles / cycles | {agent.get('icache_data_stall_cycles_percent', 0):.3f}% | {sandbox.get('icache_data_stall_cycles_percent', 0):.3f}% |",
        f"| DTLB load walk/s | {agent.get('dtlb_load_walk_completed', 0):.0f} | {sandbox.get('dtlb_load_walk_completed', 0):.0f} |",
        f"| ITLB walk/s | {agent.get('itlb_walk_completed', 0):.0f} | {sandbox.get('itlb_walk_completed', 0):.0f} |",
        *prefetch_lines,
        "",
        f"{mpki_note}`broad LLC miss event` 还包含 data/code、RFO、speculative access 和 L1/L2 hardware prefetch，不能与 retired demand-load L3 miss 混为一谈。旧版原始文件中名为 `icache_iftag_miss` 的 `0x80/0x04` 实际是 Emerald Rapids `ICACHE_DATA.STALLS`，单位是 stall cycles。",
        "",
        "### Retired load 数据来源（event / KI）",
        "",
        "| 数据来源 | host agent | sandbox |",
        "|---|---:|---:|",
        f"| L1 hit | {agent.get('mem_load_l1_hit_per_ki_estimate', 0):.3f} | {sandbox.get('mem_load_l1_hit_per_ki_estimate', 0):.3f} |",
        f"| L2 hit | {agent.get('mem_load_l2_hit_per_ki_estimate', 0):.3f} | {sandbox.get('mem_load_l2_hit_per_ki_estimate', 0):.3f} |",
        f"| L3 hit | {agent.get('mem_load_l3_hit_per_ki_estimate', 0):.3f} | {sandbox.get('mem_load_l3_hit_per_ki_estimate', 0):.3f} |",
        f"| L3 miss | {agent.get('retired_load_l3_miss_mpki_estimate', 0):.3f} | {sandbox.get('retired_load_l3_miss_mpki_estimate', 0):.3f} |",
        "",
        "### Translation、NUMA 与 memory-stall",
        "",
        "| 指标 | host agent | sandbox |",
        "|---|---:|---:|",
        f"| DTLB load STLB hit / KI | {agent.get('dtlb_load_stlb_hit_per_ki_estimate', 0):.3f} | {sandbox.get('dtlb_load_stlb_hit_per_ki_estimate', 0):.3f} |",
        f"| DTLB store STLB hit / KI | {agent.get('dtlb_store_stlb_hit_per_ki_estimate', 0):.3f} | {sandbox.get('dtlb_store_stlb_hit_per_ki_estimate', 0):.3f} |",
        f"| ITLB STLB hit / KI | {agent.get('itlb_stlb_hit_per_ki_estimate', 0):.3f} | {sandbox.get('itlb_stlb_hit_per_ki_estimate', 0):.3f} |",
        f"| local-DRAM L3-miss load / KI | {agent.get('l3_miss_local_dram_per_ki_estimate', 0):.3f} | {sandbox.get('l3_miss_local_dram_per_ki_estimate', 0):.3f} |",
        f"| remote-DRAM L3-miss load / KI | {agent.get('l3_miss_remote_dram_per_ki_estimate', 0):.3f} | {sandbox.get('l3_miss_remote_dram_per_ki_estimate', 0):.3f} |",
        f"| remote DRAM share | {agent.get('remote_dram_share_percent', 0):.3f}% | {sandbox.get('remote_dram_share_percent', 0):.3f}% |",
        f"| total stall cycles | {agent.get('cycle_activity_stalls_total_percent', 0):.2f}% | {sandbox.get('cycle_activity_stalls_total_percent', 0):.2f}% |",
        f"| L1D-miss related stall cycles | {agent.get('cycle_activity_stalls_l1d_miss_percent', 0):.2f}% | {sandbox.get('cycle_activity_stalls_l1d_miss_percent', 0):.2f}% |",
        f"| L2-miss related stall cycles | {agent.get('cycle_activity_stalls_l2_miss_percent', 0):.2f}% | {sandbox.get('cycle_activity_stalls_l2_miss_percent', 0):.2f}% |",
        f"| L3-miss related stall cycles | {agent.get('cycle_activity_stalls_l3_miss_percent', 0):.2f}% | {sandbox.get('cycle_activity_stalls_l3_miss_percent', 0):.2f}% |",
        "",
        "各级 stall 事件是重叠的逐层归因，不能相加。",
        "",
        f"- Socket0 DDR：读 {ddr.get('S0', {}).get('read_gbps', 0):.3f} GB/s，写 {ddr.get('S0', {}).get('write_gbps', 0):.3f} GB/s，总计 {ddr.get('S0', {}).get('total_gbps', 0):.3f} GB/s。",
        f"- Socket1 DDR：读 {ddr.get('S1', {}).get('read_gbps', 0):.3f} GB/s，写 {ddr.get('S1', {}).get('write_gbps', 0):.3f} GB/s，总计 {ddr.get('S1', {}).get('total_gbps', 0):.3f} GB/s。",
        "",
        "## 网络与 Token",
        "",
        f"- `ens16f0` 平均接收/发送：{physical.get('rx_kib_per_second', 0):.2f}/{physical.get('tx_kib_per_second', 0):.2f} KiB/s。",
        f"- 完整 trajectory：{tokens['trajectory_files']}；API calls：{tokens['api_calls']}。",
        f"- 可核查 token 下界：prompt {tokens.get('prompt_tokens', 0):,}，completion {tokens.get('completion_tokens', 0):,}，total {tokens.get('total_tokens', 0):,}，cached {tokens.get('cached_tokens', 0):,}。",
        "- 这是完成 trajectory 的下界，不包含停止时仍在运行、尚未落盘完整 trajectory 的请求；实际计费以 DeepSeek 控制台为准。",
        "",
        "## 调度窗口",
        "",
        f"30 秒、8 核理论容量为 240 CPU-s，记录到 {sched['total_runtime_ms'] / 1000:.3f} CPU-s。括号内数字是窗口内聚合到的同名 task 数，不是同时存活数。",
        "",
        "| comm | 累计 on-core runtime | 8 核 runtime 占比 | switches/s | 平均 on-core 片段 | average runnable delay |",
        "|---|---:|---:|---:|---:|---:|",
        *sched_rows,
        "",
        f"trace 丢失事件比例为 **{sched['lost_event_percent']:.3f}%**。平均 delay 和 runtime 分布仍可使用；max delay 容易被丢失的 wakeup/switch 配对放大，不作为结论。",
        "",
        "## 数据完整性",
        "",
        f"- PMU failed passes：{parse_kv(pmu_dir / 'result.txt').get('failed_passes')}。",
        f"- unsupported event：{parse_kv(pmu_dir / 'result.txt').get('unsupported_lines')}。",
        f"- cgroup idle samples：{parse_kv(pmu_dir / 'result.txt').get('cgroup_idle_lines')}。",
        "- `system.slice` 在 CPU0-7 上长期 idle 会产生大量 `<not counted>` 行；它表示目标 cgroup 在对应核和秒内没有运行任务，不是 PMU 事件失效。",
        "- `perf sched` 原始数据、CPU0-7 汇总报告和 CPU0 delay 过滤报告均已保留。perf 5.15 的 `-C 0` 只影响 latency 匹配，runtime/switches 列仍显示全局聚合，不能把该两列当作 CPU0 独占数据。",
    ]
    (run_dir / "formal_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(run_dir / "formal_summary.md")


if __name__ == "__main__":
    main()
