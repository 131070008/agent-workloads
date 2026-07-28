#!/usr/bin/env python3
import argparse
import csv
import json
import math
import re
import struct
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean
from typing import Any, Iterator


PCAP_MAGICS = {
    b"\xd4\xc3\xb2\xa1": "<",
    b"\xa1\xb2\xc3\xd4": ">",
    b"\x4d\x3c\xb2\xa1": "<",
    b"\xa1\xb2\x3c\x4d": ">",
}


def parse_number(value: str) -> float | None:
    value = value.strip().replace(" ", "")
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
    return "other"


def parse_fault_csv(path: Path) -> dict[str, Any]:
    totals: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    max_timestamp = 0.0
    with path.open(newline="", encoding="utf-8", errors="replace") as handle:
        for row in csv.reader(handle):
            if len(row) < 6:
                continue
            timestamp = parse_number(row[0])
            value = parse_number(row[2])
            event = row[4].strip()
            cgroup = cgroup_label(row[5].strip())
            if timestamp is None or value is None or not event:
                continue
            max_timestamp = max(max_timestamp, timestamp)
            totals[cgroup][event] += value

    duration = max_timestamp or 1.0
    result: dict[str, Any] = {"duration_seconds": duration, "cgroups": {}}
    for cgroup, events in totals.items():
        values = {}
        for event in ("page-faults", "minor-faults", "major-faults"):
            count = events.get(event, 0.0)
            values[event] = count
            values[f"{event}_per_second"] = count / duration
        split_total = values["minor-faults"] + values["major-faults"]
        values["major_share_percent"] = (
            values["major-faults"] * 100.0 / split_total if split_total else 0.0
        )
        values["total_vs_split_delta"] = values["page-faults"] - split_total
        result["cgroups"][cgroup] = values
    return result


def read_pcap(path: Path) -> Iterator[tuple[int, bytes]]:
    with path.open("rb") as handle:
        header = handle.read(24)
        if len(header) != 24 or header[:4] not in PCAP_MAGICS:
            raise ValueError(f"Unsupported or truncated pcap: {path}")
        endian = PCAP_MAGICS[header[:4]]
        linktype = struct.unpack(f"{endian}I", header[20:24])[0]
        if linktype != 1:
            raise ValueError(f"Expected Ethernet linktype 1, got {linktype}: {path}")

        while True:
            record = handle.read(16)
            if not record:
                return
            if len(record) != 16:
                raise ValueError(f"Truncated pcap record header: {path}")
            _, _, included_length, original_length = struct.unpack(
                f"{endian}IIII", record
            )
            packet = handle.read(included_length)
            if len(packet) != included_length:
                raise ValueError(f"Truncated pcap packet: {path}")
            yield original_length, packet


def parse_tcp_mss(options: bytes) -> int | None:
    index = 0
    while index < len(options):
        kind = options[index]
        if kind == 0:
            return None
        if kind == 1:
            index += 1
            continue
        if index + 1 >= len(options) or options[index + 1] < 2:
            return None
        length = options[index + 1]
        if index + length > len(options):
            return None
        if kind == 2 and length == 4:
            return int.from_bytes(options[index + 2 : index + 4], "big")
        index += length
    return None


def parse_packet(original_length: int, packet: bytes) -> dict[str, Any]:
    result: dict[str, Any] = {
        "original_length": original_length,
        "is_tcp": False,
        "is_tcp_443": False,
    }
    if len(packet) < 14:
        return result
    offset = 14
    ethertype = int.from_bytes(packet[12:14], "big")
    while ethertype in {0x8100, 0x88A8, 0x9100}:
        if len(packet) < offset + 4:
            return result
        ethertype = int.from_bytes(packet[offset + 2 : offset + 4], "big")
        offset += 4
    result["ethernet_header_length"] = offset

    if ethertype == 0x0800:
        if len(packet) < offset + 20 or packet[offset + 9] != 6:
            return result
        ip_header_length = (packet[offset] & 0x0F) * 4
        ip_total_length = int.from_bytes(packet[offset + 2 : offset + 4], "big")
        source_address = packet[offset + 12 : offset + 16]
        destination_address = packet[offset + 16 : offset + 20]
    elif ethertype == 0x86DD:
        if len(packet) < offset + 40 or packet[offset + 6] != 6:
            return result
        ip_header_length = 40
        ip_total_length = 40 + int.from_bytes(packet[offset + 4 : offset + 6], "big")
        source_address = packet[offset + 8 : offset + 24]
        destination_address = packet[offset + 24 : offset + 40]
    else:
        return result

    tcp_offset = offset + ip_header_length
    if len(packet) < tcp_offset + 20:
        return result
    source_port, destination_port = struct.unpack(">HH", packet[tcp_offset : tcp_offset + 4])
    tcp_header_length = (packet[tcp_offset + 12] >> 4) * 4
    if tcp_header_length < 20:
        return result
    flags = packet[tcp_offset + 13]
    options_end = min(len(packet), tcp_offset + tcp_header_length)
    mss = parse_tcp_mss(packet[tcp_offset + 20 : options_end]) if flags & 0x02 else None
    result.update(
        {
            "is_tcp": True,
            "is_tcp_443": source_port == 443 or destination_port == 443,
            "source_address": source_address,
            "destination_address": destination_address,
            "source_port": source_port,
            "destination_port": destination_port,
            "ip_header_length": ip_header_length,
            "tcp_header_length": tcp_header_length,
            "tcp_payload_length": max(0, ip_total_length - ip_header_length - tcp_header_length),
            "syn": bool(flags & 0x02),
            "ack": bool(flags & 0x10),
            "mss": mss,
        }
    )
    return result


def percentile(values: list[int], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(ordered[lower])
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def length_summary(frame_lengths: list[int]) -> dict[str, Any]:
    buckets = {
        "<=64": 0,
        "65-127": 0,
        "128-255": 0,
        "256-511": 0,
        "512-1023": 0,
        "1024-1518": 0,
        "1519-1522": 0,
        ">1522": 0,
    }
    for length in frame_lengths:
        if length <= 64:
            bucket = "<=64"
        elif length <= 127:
            bucket = "65-127"
        elif length <= 255:
            bucket = "128-255"
        elif length <= 511:
            bucket = "256-511"
        elif length <= 1023:
            bucket = "512-1023"
        elif length <= 1518:
            bucket = "1024-1518"
        elif length <= 1522:
            bucket = "1519-1522"
        else:
            bucket = ">1522"
        buckets[bucket] += 1

    count = len(frame_lengths)
    return {
        "count": count,
        "total_bytes": sum(frame_lengths),
        "min_bytes": min(frame_lengths) if frame_lengths else 0,
        "max_bytes": max(frame_lengths) if frame_lengths else 0,
        "mean_bytes": mean(frame_lengths) if frame_lengths else 0.0,
        "p50_bytes": percentile(frame_lengths, 0.50),
        "p90_bytes": percentile(frame_lengths, 0.90),
        "p99_bytes": percentile(frame_lengths, 0.99),
        "gt_1522_count": buckets[">1522"],
        "gt_1522_percent": buckets[">1522"] * 100.0 / count if count else 0.0,
        "buckets_including_fcs": buckets,
    }


def load_capture(path: Path) -> list[dict[str, Any]]:
    return [parse_packet(original_length, packet) for original_length, packet in read_pcap(path)]


def flow_key(packet: dict[str, Any], direction: str) -> tuple[Any, ...] | None:
    if not packet.get("is_tcp"):
        return None
    if direction == "tx":
        return (
            packet["source_address"],
            packet["source_port"],
            packet["destination_address"],
            packet["destination_port"],
        )
    return (
        packet["destination_address"],
        packet["destination_port"],
        packet["source_address"],
        packet["source_port"],
    )


def mss_maps(
    rx_packets: list[dict[str, Any]], tx_packets: list[dict[str, Any]]
) -> tuple[dict[tuple[Any, ...], int], dict[tuple[Any, ...], int], int, int]:
    local: dict[tuple[Any, ...], int] = {}
    remote: dict[tuple[Any, ...], int] = {}
    for packet in tx_packets:
        key = flow_key(packet, "tx")
        if key and packet.get("syn") and packet.get("mss"):
            local[key] = packet["mss"]
    for packet in rx_packets:
        key = flow_key(packet, "rx")
        if key and packet.get("syn") and packet.get("mss"):
            remote[key] = packet["mss"]
    default_local = Counter(local.values()).most_common(1)[0][0] if local else 1460
    default_remote = Counter(remote.values()).most_common(1)[0][0] if remote else 1460
    return local, remote, default_local, default_remote


def estimated_wire_lengths(
    packets: list[dict[str, Any]],
    direction: str,
    local_mss: dict[tuple[Any, ...], int],
    remote_mss: dict[tuple[Any, ...], int],
    default_local_mss: int,
    default_remote_mss: int,
    tcp_443_only: bool,
) -> tuple[list[int], int]:
    lengths: list[int] = []
    reconstructed_skb = 0
    for packet in packets:
        if tcp_443_only and not packet.get("is_tcp_443"):
            continue
        original_length = packet["original_length"]
        if not packet.get("is_tcp"):
            lengths.append(max(64, original_length + 4))
            continue

        key = flow_key(packet, direction)
        if direction == "tx":
            advertised_mss = remote_mss.get(key, default_remote_mss)
        else:
            advertised_mss = local_mss.get(key, default_local_mss)
        option_bytes = max(0, packet["tcp_header_length"] - 20)
        max_payload = max(1, advertised_mss - option_bytes)
        payload = packet["tcp_payload_length"]
        header_and_fcs = (
            packet["ethernet_header_length"]
            + packet["ip_header_length"]
            + packet["tcp_header_length"]
            + 4
        )

        if payload > max_payload:
            reconstructed_skb += 1
        while payload > max_payload:
            lengths.append(max(64, header_and_fcs + max_payload))
            payload -= max_payload
        lengths.append(max(64, header_and_fcs + payload))
    return lengths, reconstructed_skb


def analyze_network(
    rx_packets: list[dict[str, Any]], tx_packets: list[dict[str, Any]]
) -> dict[str, Any]:
    local_mss, remote_mss, default_local, default_remote = mss_maps(rx_packets, tx_packets)
    result: dict[str, Any] = {
        "mss": {
            "local_flows": len(local_mss),
            "remote_flows": len(remote_mss),
            "local_values": dict(Counter(local_mss.values())),
            "remote_values": dict(Counter(remote_mss.values())),
            "default_local": default_local,
            "default_remote": default_remote,
        },
        "host_capture": {},
        "estimated_wire": {},
    }
    for direction, packets in (("rx", rx_packets), ("tx", tx_packets)):
        result["host_capture"][direction] = {
            "all_traffic": length_summary([packet["original_length"] for packet in packets]),
            "tcp_443": length_summary(
                [packet["original_length"] for packet in packets if packet.get("is_tcp_443")]
            ),
        }
        result["estimated_wire"][direction] = {}
        for label, tcp_only in (("all_traffic", False), ("tcp_443", True)):
            lengths, reconstructed = estimated_wire_lengths(
                packets,
                direction,
                local_mss,
                remote_mss,
                default_local,
                default_remote,
                tcp_only,
            )
            values = length_summary(lengths)
            values["reconstructed_host_skb"] = reconstructed
            result["estimated_wire"][direction][label] = values
    return result


def parse_tcpdump_log(path: Path) -> dict[str, int]:
    text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    result = {}
    for key, pattern in (
        ("captured", r"(\d+) packets captured"),
        ("received_by_filter", r"(\d+) packets received by filter"),
        ("dropped_by_kernel", r"(\d+) packets dropped by kernel"),
    ):
        match = re.search(pattern, text)
        result[key] = int(match.group(1)) if match else 0
    return result


def render_direction(label: str, values: dict[str, Any]) -> str:
    return (
        f"| {label} | {values['count']} | {values['min_bytes']:.0f} | "
        f"{values['max_bytes']:.0f} | {values['mean_bytes']:.1f} | "
        f"{values['p50_bytes']:.1f} | {values['p90_bytes']:.1f} | "
        f"{values['p99_bytes']:.1f} | {values['gt_1522_percent']:.2f}% |"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze SWE fault and packet-length retest")
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()

    run_dir = args.run_dir.resolve()
    data_dir = run_dir / "perf_collect/fault_network"
    faults = parse_fault_csv(data_dir / "faults_by_cgroup.csv")
    rx_packets = load_capture(data_dir / "rx.pcap")
    tx_packets = load_capture(data_dir / "tx.pcap")
    network = analyze_network(rx_packets, tx_packets)
    network["tcpdump_logs"] = {
        "rx": parse_tcpdump_log(data_dir / "rx_tcpdump.log"),
        "tx": parse_tcpdump_log(data_dir / "tx_tcpdump.log"),
    }
    result = {"run_dir": str(run_dir), "faults": faults, "network": network}

    (data_dir / "fault_network_summary.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    lines = [
        "# SWE Agent/Sandbox Fault 与网络包长复测",
        "",
        "## Page fault",
        "",
        "| 执行域 | page fault/s | minor fault/s | major fault/s | major 占比 |",
        "|---|---:|---:|---:|---:|",
    ]
    labels = {
        "host_agent": "Host Agent",
        "sandbox": "Sandbox",
        "system_services": "System Services",
        "other": "Other",
    }
    for key in ("host_agent", "sandbox", "system_services", "other"):
        values = faults["cgroups"].get(key)
        if not values:
            continue
        lines.append(
            f"| {labels[key]} | {values['page-faults_per_second']:.1f} | "
            f"{values['minor-faults_per_second']:.1f} | "
            f"{values['major-faults_per_second']:.3f} | "
            f"{values['major_share_percent']:.6f}% |"
        )

    lines += [
        "",
        "`page-faults` 应与 `minor-faults + major-faults` 基本一致；表中按相同 60 秒窗口和 cgroup 汇总。",
        "",
        "## 网络包长",
        "",
        "Linux AF_PACKET 在 GRO/GSO/TSO 开启时看到的是 host-side SKB，可能包含多个线上帧。",
        "先保留原始 host capture 口径，用于观察 offload 聚合程度；再根据 TCP SYN MSS、",
        "IP/TCP header 和 MTU=1500 拆分大 SKB，并补齐 Ethernet padding 与 4-byte FCS，",
        "得到估算的线速 Ethernet frame 分布。Preamble 与 IFG 不包含在内。",
        "",
        "### Host capture：AF_PACKET/SKB 长度（不含 FCS）",
        "",
        "| 方向/流量 | 包数 | Min B | Max B | Mean B | P50 B | P90 B | P99 B | >1522B |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        render_direction("RX all", network["host_capture"]["rx"]["all_traffic"]),
        render_direction("TX all", network["host_capture"]["tx"]["all_traffic"]),
        render_direction("RX TCP/443", network["host_capture"]["rx"]["tcp_443"]),
        render_direction("TX TCP/443", network["host_capture"]["tx"]["tcp_443"]),
        "",
        "该表不能直接当作线上包长：TX 中的大量 `>1522B` 样本是 TSO/GSO 大 SKB。",
        "",
        "### 估算线速 Ethernet frame（包含 padding 和 FCS）",
        "",
        "| 方向/流量 | 帧数 | Min B | Max B | Mean B | P50 B | P90 B | P99 B | >1522B |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        render_direction("RX all", network["estimated_wire"]["rx"]["all_traffic"]),
        render_direction("TX all", network["estimated_wire"]["tx"]["all_traffic"]),
        render_direction("RX TCP/443", network["estimated_wire"]["rx"]["tcp_443"]),
        render_direction("TX TCP/443", network["estimated_wire"]["tx"]["tcp_443"]),
        "",
        f"采集窗口内识别到 local/remote MSS flow 数为 "
        f"`{network['mss']['local_flows']}/{network['mss']['remote_flows']}`；"
        f"默认 local/remote MSS 为 `{network['mss']['default_local']}/{network['mss']['default_remote']}`。",
        "",
        "### 估算线速帧长分桶（包含 FCS）",
        "",
        "| 方向/流量 | <=64 | 65-127 | 128-255 | 256-511 | 512-1023 | 1024-1518 | 1519-1522 | >1522 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for label, values in (
        ("RX all", network["estimated_wire"]["rx"]["all_traffic"]),
        ("TX all", network["estimated_wire"]["tx"]["all_traffic"]),
        ("RX TCP/443", network["estimated_wire"]["rx"]["tcp_443"]),
        ("TX TCP/443", network["estimated_wire"]["tx"]["tcp_443"]),
    ):
        buckets = values["buckets_including_fcs"]
        lines.append(
            f"| {label} | {buckets['<=64']} | {buckets['65-127']} | "
            f"{buckets['128-255']} | {buckets['256-511']} | "
            f"{buckets['512-1023']} | {buckets['1024-1518']} | "
            f"{buckets['1519-1522']} | {buckets['>1522']} |"
        )

    dropped = network["tcpdump_logs"]
    lines += [
        "",
        f"tcpdump kernel drops：RX={dropped['rx']['dropped_by_kernel']}，TX={dropped['tx']['dropped_by_kernel']}。",
        "pcap 仅保存每包前 96 byte，保留原始 frame length，不保存完整 TLS/application payload。",
        "",
    ]
    summary = "\n".join(lines)
    (data_dir / "fault_network_summary.md").write_text(summary, encoding="utf-8")
    (run_dir / "fault_network_summary.md").write_text(summary, encoding="utf-8")
    print(summary)


if __name__ == "__main__":
    main()
