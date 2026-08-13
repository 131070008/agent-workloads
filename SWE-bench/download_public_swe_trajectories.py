#!/usr/bin/env python3
"""Download selected public SWE-bench trajectories from anonymous S3."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import boto3
from botocore import UNSIGNED
from botocore.config import Config


BUCKET = "swe-bench-submissions"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--submission", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--max-retries", type=int, default=0,
                        help="Retries per object; 0 means retry indefinitely")
    return parser.parse_args()


def load_instance_ids(manifest_path: Path) -> list[str]:
    with manifest_path.open(encoding="utf-8") as handle:
        manifest = json.load(handle)
    cases = manifest.get("cases")
    if not isinstance(cases, list):
        raise ValueError(f"{manifest_path}: expected a cases list")
    instance_ids = [case["instance_id"] for case in cases]
    if len(instance_ids) != len(set(instance_ids)):
        raise ValueError(f"{manifest_path}: duplicate instance_id values")
    return instance_ids


def list_objects(s3, submission: str, instance_id: str) -> list[dict]:
    prefix = f"lite/{submission}/trajs/{instance_id}/"
    objects: list[dict] = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=BUCKET, Prefix=prefix):
        objects.extend(page.get("Contents", []))
    return sorted(objects, key=lambda item: item["Key"])


def preserve_invalid(path: Path, invalid_dir: Path) -> None:
    invalid_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = invalid_dir / f"{path.name}.invalid-{stamp}"
    suffix = 1
    while target.exists():
        target = invalid_dir / f"{path.name}.invalid-{stamp}-{suffix}"
        suffix += 1
    shutil.move(str(path), target)
    print(f"PRESERVED_INVALID {path} -> {target}", flush=True)


def download_object(
    s3,
    obj: dict,
    destination: Path,
    invalid_dir: Path,
    max_retries: int,
) -> None:
    expected_size = int(obj["Size"])
    if destination.exists() and destination.stat().st_size == expected_size:
        print(f"SKIP {destination.name} bytes={expected_size}", flush=True)
        return
    if destination.exists():
        preserve_invalid(destination, invalid_dir)

    destination.parent.mkdir(parents=True, exist_ok=True)
    attempt = 0
    while True:
        attempt += 1
        try:
            print(
                f"DOWNLOAD attempt={attempt} bytes={expected_size} "
                f"s3://{BUCKET}/{obj['Key']}",
                flush=True,
            )
            s3.download_file(BUCKET, obj["Key"], str(destination))
            actual_size = destination.stat().st_size
            if actual_size != expected_size:
                preserve_invalid(destination, invalid_dir)
                raise OSError(
                    f"size mismatch for {destination}: "
                    f"expected {expected_size}, got {actual_size}"
                )
            print(f"DONE {destination} bytes={actual_size}", flush=True)
            return
        except Exception as exc:  # Network failures vary across boto3 versions.
            if destination.exists():
                preserve_invalid(destination, invalid_dir)
            if max_retries and attempt >= max_retries:
                raise
            delay = min(300, 5 * (2 ** min(attempt - 1, 6)))
            print(
                f"RETRY attempt={attempt} delay={delay}s error={exc!r}",
                file=sys.stderr,
                flush=True,
            )
            time.sleep(delay)


def main() -> int:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    lock_path = args.output_dir / ".download.lock"
    lock_handle = lock_path.open("w", encoding="utf-8")
    try:
        fcntl.flock(lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print(f"Another downloader holds {lock_path}", file=sys.stderr)
        return 2
    lock_handle.write(f"pid={os.getpid()}\n")
    lock_handle.flush()

    instance_ids = load_instance_ids(args.manifest)
    s3 = boto3.client(
        "s3",
        config=Config(
            signature_version=UNSIGNED,
            retries={"max_attempts": 10, "mode": "adaptive"},
        ),
    )

    plan: list[dict] = []
    for instance_id in instance_ids:
        objects = list_objects(s3, args.submission, instance_id)
        if not objects:
            raise RuntimeError(f"No public trajectory objects for {instance_id}")
        plan.append({"instance_id": instance_id, "objects": objects})

    total_objects = sum(len(item["objects"]) for item in plan)
    total_bytes = sum(int(obj["Size"]) for item in plan for obj in item["objects"])
    print(
        f"PLAN cases={len(plan)} objects={total_objects} bytes={total_bytes} "
        f"submission={args.submission}",
        flush=True,
    )

    completed: list[dict] = []
    for case_index, item in enumerate(plan, start=1):
        instance_id = item["instance_id"]
        case_dir = args.output_dir / instance_id
        invalid_dir = args.output_dir / ".invalid" / instance_id
        print(
            f"CASE {case_index}/{len(plan)} {instance_id} "
            f"objects={len(item['objects'])}",
            flush=True,
        )
        case_records = []
        for obj in item["objects"]:
            destination = case_dir / Path(obj["Key"]).name
            download_object(s3, obj, destination, invalid_dir, args.max_retries)
            case_records.append(
                {
                    "s3_key": obj["Key"],
                    "local_file": str(destination.relative_to(args.output_dir)),
                    "size": int(obj["Size"]),
                    "etag": obj.get("ETag", "").strip('"'),
                }
            )
        completed.append({"instance_id": instance_id, "objects": case_records})

    result = {
        "format_version": 1,
        "bucket": BUCKET,
        "submission": args.submission,
        "source_manifest": str(args.manifest),
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "cases": completed,
        "summary": {
            "case_count": len(completed),
            "object_count": total_objects,
            "total_bytes": total_bytes,
        },
    }
    result_path = args.output_dir / "download_manifest.json"
    with result_path.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    complete_path = args.output_dir / "DOWNLOAD_COMPLETE"
    with complete_path.open("x", encoding="utf-8") as handle:
        handle.write(
            f"cases={len(completed)} objects={total_objects} "
            f"bytes={total_bytes}\n"
        )
    print(f"COMPLETE manifest={result_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
