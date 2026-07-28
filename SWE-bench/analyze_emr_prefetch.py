#!/usr/bin/env python3
import argparse
import json
from pathlib import Path
from typing import Any

from analyze_formal_swe_pmu import aggregate_ddr, aggregate_perf_events


def ratio(numerator: float, denominator: float) -> float:
    return 100.0 * numerator / denominator if denominator else 0.0


def per_ki(event_count: float, instructions: float) -> float:
    return 1000.0 * event_count / instructions if instructions else 0.0


def derive(groups: dict[str, dict[str, float]]) -> dict[str, float]:
    hw = groups.get("hw_prefetch", {})
    demand = groups.get("demand_and_lines", {})
    sw = groups.get("software_prefetch", {})
    pressure = groups.get("fill_buffer_pressure", {})
    offcore_demand_l1d = groups.get("offcore_demand_l1d", {})
    offcore_l2_demand_l3 = groups.get("offcore_l2_demand_l3", {})
    offcore_l3 = groups.get("offcore_l3", {})
    sw_types = groups.get("software_prefetch_types", {})
    hw_ins = hw.get("instructions", 0.0)
    demand_ins = demand.get("instructions", 0.0)
    sw_ins = sw.get("instructions", 0.0)
    pressure_cycles = pressure.get("cycles", 0.0)
    offcore_demand_l1d_ins = offcore_demand_l1d.get("instructions", 0.0)
    offcore_l2_demand_l3_ins = offcore_l2_demand_l3.get("instructions", 0.0)
    offcore_l3_ins = offcore_l3.get("instructions", 0.0)
    sw_types_ins = sw_types.get("instructions", 0.0)
    l2_hwpf_miss = hw.get("l2_hwpf_miss", 0.0)
    l2_useless_hwpf = hw.get("l2_useless_hwpf", 0.0)
    l3_hwpf_responses = offcore_l3.get("ocr_hwpf_l3_l3_hit", 0.0) + offcore_l3.get(
        "ocr_hwpf_l3_l3_miss", 0.0
    )

    return {
        "l1d_hwpf_miss_per_ki": per_ki(hw.get("l1d_hwpf_miss", 0.0), hw_ins),
        "l2_hwpf_request_per_ki": per_ki(hw.get("l2_hwpf_all", 0.0), hw_ins),
        "l2_hwpf_miss_per_ki": per_ki(hw.get("l2_hwpf_miss", 0.0), hw_ins),
        "l2_useless_hwpf_eviction_per_ki": per_ki(hw.get("l2_useless_hwpf", 0.0), hw_ins),
        "l2_hwpf_miss_percent": ratio(hw.get("l2_hwpf_miss", 0.0), hw.get("l2_hwpf_all", 0.0)),
        "l2_useless_per_100_hwpf_request_proxy": ratio(
            l2_useless_hwpf, hw.get("l2_hwpf_all", 0.0)
        ),
        "l2_useless_per_100_hwpf_miss_fill_proxy": ratio(
            l2_useless_hwpf, l2_hwpf_miss
        ),
        "l2_lines_in_per_ki": per_ki(demand.get("l2_lines_in", 0.0), demand_ins),
        "l2_demand_miss_mpki": per_ki(demand.get("l2_demand_data_read_miss", 0.0), demand_ins),
        "l2_demand_miss_percent": ratio(
            demand.get("l2_demand_data_read_miss", 0.0),
            demand.get("l2_demand_data_read", 0.0),
        ),
        "offcore_l3_miss_demand_data_read_mpki": per_ki(
            demand.get("offcore_l3_miss_demand_data_read", 0.0), demand_ins
        ),
        "l2_swpf_hit_per_ki": per_ki(sw.get("l2_swpf_hit", 0.0), sw_ins),
        "l2_swpf_miss_per_ki": per_ki(sw.get("l2_swpf_miss", 0.0), sw_ins),
        "swpf_miss_percent": ratio(sw.get("l2_swpf_miss", 0.0), sw.get("l2_swpf_hit", 0.0) + sw.get("l2_swpf_miss", 0.0)),
        "load_hit_prefetch_swpf_per_ki": per_ki(sw.get("load_hit_prefetch_swpf", 0.0), sw_ins),
        "sw_prefetch_instruction_per_ki": per_ki(sw.get("sw_prefetch_access_any", 0.0), sw_ins),
        "average_l1d_pending": pressure.get("l1d_pending", 0.0) / pressure_cycles
        if pressure_cycles
        else 0.0,
        "l1d_pending_cycle_percent": ratio(
            pressure.get("l1d_pending_cycles", 0.0), pressure_cycles
        ),
        "l1d_fb_full_cycle_percent": ratio(
            pressure.get("l1d_fb_full_cycles", 0.0), pressure_cycles
        ),
        "l1d_l2_stall_cycle_percent": ratio(
            pressure.get("l1d_l2_stall_cycles", 0.0), pressure_cycles
        ),
        "ocr_demand_data_per_ki": per_ki(
            offcore_demand_l1d.get("ocr_demand_data_any", 0.0), offcore_demand_l1d_ins
        ),
        "ocr_hwpf_l1d_per_ki": per_ki(
            offcore_demand_l1d.get("ocr_hwpf_l1d_any", 0.0), offcore_demand_l1d_ins
        ),
        "ocr_hwpf_l2_per_ki": per_ki(
            offcore_l2_demand_l3.get("ocr_hwpf_l2_any", 0.0), offcore_l2_demand_l3_ins
        ),
        "ocr_hwpf_l3_hit_per_ki": per_ki(
            offcore_l3.get("ocr_hwpf_l3_l3_hit", 0.0), offcore_l3_ins
        ),
        "ocr_hwpf_l3_miss_per_ki": per_ki(
            offcore_l3.get("ocr_hwpf_l3_l3_miss", 0.0), offcore_l3_ins
        ),
        "ocr_demand_data_l3_miss_mpki": per_ki(
            offcore_l2_demand_l3.get("ocr_demand_data_l3_miss", 0.0),
            offcore_l2_demand_l3_ins,
        ),
        "ocr_hwpf_l3_miss_percent": ratio(
            offcore_l3.get("ocr_hwpf_l3_l3_miss", 0.0), l3_hwpf_responses
        ),
        "sw_prefetch_nta_per_ki": per_ki(sw_types.get("sw_prefetch_nta", 0.0), sw_types_ins),
        "sw_prefetch_t0_per_ki": per_ki(sw_types.get("sw_prefetch_t0", 0.0), sw_types_ins),
        "sw_prefetch_t1_t2_per_ki": per_ki(
            sw_types.get("sw_prefetch_t1_t2", 0.0), sw_types_ins
        ),
        "sw_prefetch_w_per_ki": per_ki(sw_types.get("sw_prefetch_w", 0.0), sw_types_ins),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize Emerald Rapids prefetch PMU passes")
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    output_dir = args.output_dir.resolve()

    globs = {
        "hw_prefetch": "round*_01_hw_prefetch.csv",
        "demand_and_lines": "round*_02_demand_and_lines.csv",
        "software_prefetch": "round*_03_software_prefetch.csv",
        "fill_buffer_pressure": "round*_04_fill_buffer_pressure.csv",
        "offcore_demand_l1d": "round*_05_offcore_demand_l1d.csv",
        "offcore_l2_demand_l3": "round*_06_offcore_l2_demand_l3.csv",
        "offcore_l3": "round*_07_offcore_l3.csv",
        "software_prefetch_types": "round*_08_software_prefetch_types.csv",
    }
    by_cgroup: dict[str, dict[str, dict[str, float]]] = {}
    for group_name, pattern in globs.items():
        values = aggregate_perf_events(sorted(output_dir.glob(pattern)))
        for cgroup, events in values.items():
            by_cgroup.setdefault(cgroup, {})[group_name] = events

    derived = {cgroup: derive(groups) for cgroup, groups in by_cgroup.items()}
    ddr = aggregate_ddr(output_dir / "ddr_imc.csv")
    result: dict[str, Any] = {
        "output_dir": str(output_dir),
        "raw_event_rate_per_second": by_cgroup,
        "derived_same_pass_metrics": derived,
        "ddr": ddr,
    }
    (output_dir / "prefetch_summary.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    agent = derived.get("host_agent", {})
    sandbox = derived.get("sandbox", {})

    def row(label: str, key: str, suffix: str = "") -> str:
        return f"| {label} | {agent.get(key, 0):.3f}{suffix} | {sandbox.get(key, 0):.3f}{suffix} |"

    lines = [
        "# Emerald Rapids 预取 PMU 摘要",
        "",
        "## 硬件预取活动与浪费",
        "",
        "| 指标 | host agent | sandbox |",
        "|---|---:|---:|",
        row("L1D HWPF miss / KI", "l1d_hwpf_miss_per_ki"),
        row("L2 HWPF request / KI", "l2_hwpf_request_per_ki"),
        row("L2 HWPF true miss / KI", "l2_hwpf_miss_per_ki"),
        row("L2 unused-prefetch eviction / KI", "l2_useless_hwpf_eviction_per_ki"),
        row("L2 HWPF true miss / request", "l2_hwpf_miss_percent", "%"),
        row("unused eviction / HWPF request（代理值）", "l2_useless_per_100_hwpf_request_proxy", "%"),
        row("unused eviction / HWPF true miss（近似 fill waste）", "l2_useless_per_100_hwpf_miss_fill_proxy", "%"),
        "",
        "`HWPF true miss` 表示预取请求需要从 L2 以下层级取数，不等于预取失败；`unused-prefetch eviction` 才明确表示某条预取线直到被 L2 驱逐仍未被 demand 使用。后者与 request/fill 的生命周期可能跨越采集窗口，因此两个代理比值都不能当作精确 accuracy。",
        "",
        "## Demand 与各级硬件预取的 Offcore 流量",
        "",
        "| 请求发起者 | host agent | sandbox |",
        "|---|---:|---:|",
        row("Demand data any-response / KI", "ocr_demand_data_per_ki"),
        row("L1D HW prefetch any-response / KI", "ocr_hwpf_l1d_per_ki"),
        row("L2 HW prefetch any-response / KI", "ocr_hwpf_l2_per_ki"),
        row("L3-only HW prefetch L3-hit / KI", "ocr_hwpf_l3_hit_per_ki"),
        row("L3-only HW prefetch L3-miss / KI", "ocr_hwpf_l3_miss_per_ki"),
        row("Demand data L3-miss MPKI", "ocr_demand_data_l3_miss_mpki"),
        row("L3-only HW prefetch L3-miss / response", "ocr_hwpf_l3_miss_percent", "%"),
        "",
        "Offcore Response 按请求发起者区分 demand、L1D prefetch、L2 prefetch 和 L3-only prefetch；L3 hit/miss 反映预取数据来自哪里，仍不等于该数据后来是否被 demand 使用。",
        "",
        "## Demand miss 与填充压力",
        "",
        "| 指标 | host agent | sandbox |",
        "|---|---:|---:|",
        row("L2 demand miss MPKI", "l2_demand_miss_mpki"),
        row("L2 demand miss / request", "l2_demand_miss_percent", "%"),
        row("offcore L3-miss demand-read MPKI", "offcore_l3_miss_demand_data_read_mpki"),
        row("L2 lines-in / KI", "l2_lines_in_per_ki"),
        row("平均 outstanding L1D miss", "average_l1d_pending"),
        row("存在 outstanding L1D miss 的周期", "l1d_pending_cycle_percent", "%"),
        row("L1D fill-buffer full 周期", "l1d_fb_full_cycle_percent", "%"),
        row("L1D 因 L2 资源不足停顿周期", "l1d_l2_stall_cycle_percent", "%"),
        "",
        "## 软件预取",
        "",
        "| 指标 | host agent | sandbox |",
        "|---|---:|---:|",
        row("L2 SW prefetch hit / KI", "l2_swpf_hit_per_ki"),
        row("L2 SW prefetch miss / KI", "l2_swpf_miss_per_ki"),
        row("SW prefetch miss / request", "swpf_miss_percent", "%"),
        row("load hit SW-prefetch fill buffer / KI", "load_hit_prefetch_swpf_per_ki"),
        row("executed SW-prefetch instruction / KI", "sw_prefetch_instruction_per_ki"),
        row("PREFETCHNTA / KI", "sw_prefetch_nta_per_ki"),
        row("PREFETCHT0 / KI", "sw_prefetch_t0_per_ki"),
        row("PREFETCHT1/T2 / KI", "sw_prefetch_t1_t2_per_ki"),
        row("PREFETCHW / KI", "sw_prefetch_w_per_ki"),
        "",
        "`LOAD_HIT_PREFETCH.SWPF` 也可能被部分 lock 指令增加，只有配合采样和汇编检查才能严格归因。",
        "",
        "## DDR",
        "",
        f"- Socket0：{ddr.get('S0', {}).get('total_gbps', 0):.3f} GB/s。",
        f"- Socket1：{ddr.get('S1', {}).get('total_gbps', 0):.3f} GB/s。",
        "",
        "## 判断口径",
        "",
        "这组计数能回答预取器是否活跃、demand 与各级 prefetch 分别产生多少 lower-level traffic、以及有多少 L2 预取线明确未被使用，但单次默认配置仍不能完整区分 accurate prefetch 中的 timely 与 late，也不能证明净收益。late prefetch 仍然预测正确，只是 demand 到达时数据还在路上。严格判断需要在相同 workload 上逐项开关 L1 DCU streamer、L1 DCU IP、L2 streamer 和 L2 adjacent-line prefetcher，比较任务吞吐/耗时、demand MPKI、memory-stall、unused-prefetch eviction 与 DDR 带宽。",
    ]
    (output_dir / "prefetch_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(output_dir / "prefetch_summary.md")


if __name__ == "__main__":
    main()
