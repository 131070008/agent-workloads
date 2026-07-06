#!/usr/bin/env python3
"""Run one official SWE-bench Lite case with mini-SWE-agent.

This uses the local SWE-bench Lite test Arrow file already stored in this
workload directory, so it does not need Hugging Face network access at runtime.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from datasets import Dataset
from minisweagent.config import get_config_from_spec
from minisweagent.run.benchmarks.swebench import process_instance
from minisweagent.run.benchmarks.utils.batch_progress import RunBatchProgressManager
from minisweagent.utils.serialize import recursive_merge


ROOT = Path(__file__).resolve().parents[1]
WORKLOAD_DIR = Path(__file__).resolve().parent
DEFAULT_ARROW = WORKLOAD_DIR / "datasets/swe_bench_lite_smoke/raw/swe-bench_lite-test.arrow"


def main() -> None:
    instance_id = os.environ.get("SWE_INSTANCE_ID", "astropy__astropy-12907")
    output_dir = Path(os.environ.get("SWE_OUTPUT_DIR", str(Path.home() / "cunzhe/swe_runs/swe_lite_official_one")))
    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    dataset = Dataset.from_file(str(Path(os.environ.get("SWE_ARROW", str(DEFAULT_ARROW)))))
    instance = next((dict(row) for row in dataset if row["instance_id"] == instance_id), None)
    if instance is None:
        raise SystemExit(f"SWE-bench Lite instance not found: {instance_id}")

    run_args = ["--rm"]
    if cpuset := os.environ.get("SWE_CONTAINER_CPUSET", "").strip():
        run_args.append(f"--cpuset-cpus={cpuset}")

    config = recursive_merge(
        get_config_from_spec(os.environ.get("SWE_CONFIG", "swebench_backticks.yaml")),
        {
            "agent": {
                "step_limit": int(os.environ.get("SWE_STEP_LIMIT", "40")),
                "cost_limit": 0.0,
            },
            "environment": {
                "environment_class": "docker",
                "run_args": run_args,
                "env": {"BASH_ENV": "/root/.bashrc"},
            },
            "model": {
                "model_name": os.environ.get("SWE_MODEL", "openai/glm-4.5-air"),
                "model_class": "litellm_textbased",
                "cost_tracking": "ignore_errors",
                "model_kwargs": {
                    "temperature": float(os.environ.get("SWE_TEMPERATURE", "0")),
                    "max_tokens": int(os.environ.get("SWE_MAX_TOKENS", "4096")),
                    "drop_params": True,
                    "api_base": os.environ.get("OPENAI_API_BASE", "https://open.bigmodel.cn/api/paas/v4"),
                },
            },
        },
    )

    meta = {
        "instance_id": instance["instance_id"],
        "repo": instance["repo"],
        "base_commit": instance["base_commit"],
        "problem_statement_chars": len(instance["problem_statement"]),
        "output_dir": str(output_dir),
        "model": config["model"]["model_name"],
        "step_limit": config["agent"]["step_limit"],
        "container_run_args": run_args,
        "started_at": time.time(),
    }
    (output_dir / "run_meta_start.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print("RUN_META", json.dumps(meta, ensure_ascii=False), flush=True)
    print("PROBLEM_PREVIEW", instance["problem_statement"][:800].replace("\n", "\\n"), flush=True)

    progress = RunBatchProgressManager(1, output_dir / f"exit_statuses_{time.time()}.yaml")
    process_instance(instance, output_dir, config, progress)

    preds = output_dir / "preds.json"
    print("PREDS_EXISTS", preds.exists(), flush=True)
    if preds.exists():
        data = json.loads(preds.read_text())
        pred = data.get(instance_id, {})
        patch = pred.get("model_patch") or ""
        print("PATCH_CHARS", len(patch), flush=True)
        print("PATCH_PREVIEW", patch[:1200].replace("\n", "\\n"), flush=True)

    traj = output_dir / instance_id / f"{instance_id}.traj.json"
    print("TRAJ", str(traj), traj.exists(), flush=True)
    if traj.exists():
        obj = json.loads(traj.read_text())
        print("TRAJ_INFO", json.dumps(obj.get("info", {}), ensure_ascii=False)[:2000], flush=True)


if __name__ == "__main__":
    main()
