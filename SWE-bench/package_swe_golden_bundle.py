#!/usr/bin/env python3
"""Package shared SWE images and Flash/Pro Golden trajectories for transfer."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tarfile
import time
from pathlib import Path
from typing import Any


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def image_references(manifest: dict[str, Any]) -> list[str]:
    return list(dict.fromkeys(case["image"] for case in manifest["cases"] if case.get("image")))


def add_tree(archive: tarfile.TarFile, source: Path, destination: str) -> None:
    if source.exists():
        archive.add(source, arcname=destination, recursive=True)


def write_helpers(output_dir: Path) -> None:
    (output_dir / "load_bundle.sh").write_text(
        """#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
cd "$ROOT"

sha256sum -c SHA256SUMS
cat images.tar.zst.part-* | zstd -dc | docker load
mkdir -p extracted
tar -xzf golden_metadata.tar.gz -C extracted
python3 verify_images.py

echo "Golden metadata: $ROOT/extracted/golden"
""",
        encoding="utf-8",
    )
    (output_dir / "verify_bundle.sh").write_text(
        """#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
cd "$ROOT"
sha256sum -c SHA256SUMS
""",
        encoding="utf-8",
    )
    (output_dir / "verify_images.py").write_text(
        """#!/usr/bin/env python3
import json
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parent
manifest = json.loads((root / "bundle_manifest.json").read_text(encoding="utf-8"))
failures = []
for image in manifest["images"]:
    completed = subprocess.run(
        ["docker", "image", "inspect", image["reference"], "--format", "{{.Id}}"],
        text=True,
        capture_output=True,
        check=False,
    )
    actual = completed.stdout.strip()
    if completed.returncode != 0 or actual != image["image_id"]:
        failures.append({"reference": image["reference"], "expected": image["image_id"], "actual": actual})
if failures:
    raise SystemExit("Image verification failed: " + json.dumps(failures, ensure_ascii=False))
print(f"Verified {len(manifest['images'])} Docker images")
""",
        encoding="utf-8",
    )
    for name in ("load_bundle.sh", "verify_bundle.sh", "verify_images.py"):
        (output_dir / name).chmod(0o755)


def write_readme(output_dir: Path) -> None:
    (output_dir / "README.md").write_text(
        """# SWE Golden 可迁移包

本目录包含一份 Flash/Pro 共用的 30 个 `linux/amd64` SWE-bench Docker 镜像，
以及两组 Golden trajectory、manifest、evaluator 和 replay 汇总。镜像只保存
一次；Flash 与 Pro 的差异只存在于 metadata 小包中。

## 复制

建议逐个复制 4 GiB 分片，失败时只需重传对应文件：

```bash
scp -p images.tar.zst.part-* golden_metadata.tar.gz bundle_manifest.json \\
  SHA256SUMS load_bundle.sh verify_bundle.sh verify_images.py README.md \\
  USER@TARGET:/path/to/swe_golden_bundle/
```

## 目标机导入

```bash
cd /path/to/swe_golden_bundle
./verify_bundle.sh
./load_bundle.sh
```

`load_bundle.sh` 会流式执行 `zstd -dc | docker load`，不会额外生成完整 tar；
metadata 解压到 `extracted/`。导入后还会按照 image ID 校验 30 个镜像。

跨平台性能与吞吐对比使用 `delay_scale=0`，删除 LLM 等待；PMU、Top-down 等
微架构采集使用 `delay_scale=1`，保留 Golden 轨迹记录的模型反压节奏。两类实验
都不以 resolved 结果筛选 workload，也不采集网络包。
""",
        encoding="utf-8",
    )


def create_metadata_archive(
    output_dir: Path,
    flash_dir: Path,
    pro_dir: Path,
    comparison_dir: Path,
    flash_evaluator: Path | None,
    pro_evaluator: Path | None,
    flash_replay: Path | None,
    pro_replay: Path | None,
    tools_dir: Path | None,
) -> None:
    with tarfile.open(output_dir / "golden_metadata.tar.gz", "w:gz") as archive:
        add_tree(archive, flash_dir, "golden/flash")
        add_tree(archive, pro_dir, "golden/pro")
        add_tree(archive, comparison_dir, "golden/comparison")
        for source, destination in (
            (flash_evaluator, "evaluator/flash.json"),
            (pro_evaluator, "evaluator/pro.json"),
            (flash_replay, "replay/flash_summary.json"),
            (pro_replay, "replay/pro_summary.json"),
        ):
            if source and source.exists():
                archive.add(source, arcname=destination)
        if tools_dir and tools_dir.exists():
            for name in (
                "README.md",
                "replay_swe_trajectory.py",
                "run_swe_golden_replay.py",
                "run_swe_golden_single_perf.sh",
                "run_swe_golden_multi_perf.sh",
                "run_swe_golden_rate.py",
                "run_swe_golden_rate_perf.sh",
                "run_swe_golden_fixed_sweep.sh",
                "compare_swe_golden_concurrency.py",
                "render_swe_golden_case_report.py",
                "summarize_swe_golden_perf.py",
                "swe_replay_model.py",
                "swe_replay_environment.py",
                "compare_swe_golden_sets.py",
            ):
                source = tools_dir / name
                if source.exists():
                    archive.add(source, arcname=f"tools/SWE-bench/{name}")
            arrow = tools_dir / "datasets/swe_bench_lite_smoke/raw/swe-bench_lite-test.arrow"
            if arrow.exists():
                archive.add(arrow, arcname="tools/SWE-bench/datasets/swe-bench_lite-test.arrow")


def stream_images(output_dir: Path, references: list[str], threads: int, split_size: str) -> None:
    prefix = str(output_dir / "images.tar.zst.part-")
    docker = subprocess.Popen(["docker", "save", *references], stdout=subprocess.PIPE)
    assert docker.stdout is not None
    zstd = subprocess.Popen(
        ["zstd", f"-T{threads}", "-3", "-c"],
        stdin=docker.stdout,
        stdout=subprocess.PIPE,
    )
    docker.stdout.close()
    assert zstd.stdout is not None
    split = subprocess.Popen(
        ["split", "-b", split_size, "-d", "-a", "3", "-", prefix],
        stdin=zstd.stdout,
    )
    zstd.stdout.close()
    split_rc = split.wait()
    zstd_rc = zstd.wait()
    docker_rc = docker.wait()
    if docker_rc or zstd_rc or split_rc:
        raise RuntimeError(
            f"image archive pipeline failed: docker={docker_rc} zstd={zstd_rc} split={split_rc}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--flash-dir", type=Path, required=True)
    parser.add_argument("--pro-dir", type=Path, required=True)
    parser.add_argument("--comparison-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--flash-evaluator", type=Path)
    parser.add_argument("--pro-evaluator", type=Path)
    parser.add_argument("--flash-replay", type=Path)
    parser.add_argument("--pro-replay", type=Path)
    parser.add_argument("--tools-dir", type=Path)
    parser.add_argument("--zstd-threads", type=int, default=8)
    parser.add_argument("--split-size", default="4096M")
    args = parser.parse_args()

    output_dir = args.output_dir.expanduser().absolute()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise SystemExit(f"output directory is not empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    flash_dir = args.flash_dir.expanduser().resolve()
    pro_dir = args.pro_dir.expanduser().resolve()
    flash = read_json(flash_dir / "manifest.json")
    pro = read_json(pro_dir / "manifest.json")
    flash_refs = image_references(flash)
    pro_refs = image_references(pro)
    if flash_refs != pro_refs:
        raise SystemExit("Flash and Pro image reference lists differ")
    if len(flash_refs) != 30:
        raise SystemExit(f"expected 30 images, found {len(flash_refs)}")

    images = []
    for reference in flash_refs:
        flash_image = flash["images"][reference]
        pro_image = pro["images"][reference]
        if flash_image.get("image_id") != pro_image.get("image_id"):
            raise SystemExit(f"Flash/Pro image ID mismatch: {reference}")
        images.append(
            {
                "reference": reference,
                "image_id": flash_image.get("image_id"),
                "repo_digests": flash_image.get("repo_digests") or [],
                "platform": flash_image.get("platform"),
                "size_bytes": flash_image.get("size_bytes"),
            }
        )

    manifest = {
        "format_version": 1,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "layout": {
            "metadata": "golden_metadata.tar.gz",
            "images": "images.tar.zst.part-*",
            "image_stream": "docker save | zstd -3 | split",
        },
        "models": {
            "flash": flash.get("aggregate"),
            "pro": pro.get("aggregate"),
        },
        "images": images,
    }
    (output_dir / "bundle_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output_dir / "image_references.txt").write_text("\n".join(flash_refs) + "\n", encoding="utf-8")
    write_helpers(output_dir)
    write_readme(output_dir)
    create_metadata_archive(
        output_dir,
        flash_dir,
        pro_dir,
        args.comparison_dir.expanduser().resolve(),
        args.flash_evaluator.expanduser().resolve() if args.flash_evaluator else None,
        args.pro_evaluator.expanduser().resolve() if args.pro_evaluator else None,
        args.flash_replay.expanduser().resolve() if args.flash_replay else None,
        args.pro_replay.expanduser().resolve() if args.pro_replay else None,
        args.tools_dir.expanduser().resolve() if args.tools_dir else None,
    )
    stream_images(output_dir, flash_refs, args.zstd_threads, args.split_size)

    parts = sorted(output_dir.glob("images.tar.zst.part-*"))
    summary = {
        "output_dir": str(output_dir),
        "image_count": len(images),
        "parts": [path.name for path in parts],
        "image_archive_bytes": sum(path.stat().st_size for path in parts),
        "metadata_bytes": (output_dir / "golden_metadata.tar.gz").stat().st_size,
    }
    (output_dir / "PACKAGE_COMPLETE.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    checksum_files = sorted(
        path for path in output_dir.iterdir() if path.is_file() and path.name != "SHA256SUMS"
    )
    (output_dir / "SHA256SUMS").write_text(
        "".join(f"{sha256_file(path)}  {path.name}\n" for path in checksum_files),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
