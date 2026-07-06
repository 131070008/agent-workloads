# SWE-bench Workload

This directory collects SWE-bench workload inputs and harness drivers.

# TODO Before Formal Benchmark Analysis

The current local run is a path-validation smoke. Before using this workload
for formal CPU agent workload analysis, run a larger standard SWE-bench subset
and score patches with the official evaluation flow.

Required next steps:

- Run a meaningful subset of SWE-bench Lite or SWE-bench Verified, not only the
  single `pallets__flask-4045` smoke case.
- Use local LLM runs first, then optionally compare with cloud models.
- Add official patch validation / grading so results report solved rate, not
  only `Submitted`.
- Record E2E latency, agent step count, shell/python/test execution time,
  patch size, retry count, and pass/fail reason.
- Keep single-case smoke runs only as path validation, not as formal benchmark
  evidence.

## What This Benchmark Does

This benchmark represents a coding-agent workload. The agent receives a real
GitHub issue or bug-fix task from SWE-bench, explores the repository, edits
code, runs shell/python/test commands, and submits a patch. The benchmark then
checks whether the patch fixes the issue.

Typical tasks:

- fix a failing behavior in an existing Python project
- inspect source files, tests, and error messages
- run commands in a sandbox or local environment
- generate and validate a code patch

Important distinction:

- SWE-bench / SWE-bench Lite / SWE-bench Verified: benchmark datasets.
- mini-swe-agent / SWE-agent / OpenHands / Codex-style agents: agent runners.
- This folder: local workload harness and case manifests for running standard
  SWE-style tasks in a controlled way.

## First Workload

The first supported workload is `swe_bench_lite_smoke`:

```text
dataset: SWE-bench Lite
split: test
cases: 300
local smoke case: pallets__flask-4045
```

The local smoke case has already been run successfully with Ollama/Qwen:

```text
instance: pallets__flask-4045
status: Submitted
wall time: 925.9s
```

## Run

List local smoke cases:

```bash
workloads/SWE-bench/run_swe_lite_smoke.sh --list-cases
```

Dry-run the command without invoking the model:

```bash
workloads/SWE-bench/run_swe_lite_smoke.sh --dry-run
```

Run the default smoke case:

```bash
workloads/SWE-bench/run_swe_lite_smoke.sh
```

Run one official SWE-bench Lite case from the local 300-case test split. This
does not use the 20-case smoke manifest.

```bash
cd ~/cunzhe/agent-workloads
set -a
. ~/cunzhe/.secrets/zhipu.env
set +a

SWE_INSTANCE_ID=astropy__astropy-12907 \
SWE_OUTPUT_DIR=~/cunzhe/swe_runs/swe_lite_official_one \
SWE_STEP_LIMIT=40 \
SWE_AGENT_CORE=1 \
SWE_CONTAINER_CPUSET=2 \
SWE-bench/run_swe_lite_official_case.sh
```

Evaluate the generated patch with the official SWE-bench harness:

```bash
cd ~/cunzhe/agent-workloads
.venv-swe/bin/python - <<'PY'
import json
from pathlib import Path
from datasets import Dataset

repo = Path.home() / "cunzhe/agent-workloads"
out = Path.home() / "cunzhe/swe_runs/swe_lite_official_one"
iid = "astropy__astropy-12907"
ds = Dataset.from_file(str(repo / "SWE-bench/datasets/swe_bench_lite_smoke/raw/swe-bench_lite-test.arrow"))
row = next(dict(r) for r in ds if r["instance_id"] == iid)
(out / "dataset_one.json").write_text(json.dumps([row], ensure_ascii=False, indent=2), encoding="utf-8")
PY

.venv-swe/bin/python -m swebench.harness.run_evaluation \
  --dataset_name ~/cunzhe/swe_runs/swe_lite_official_one/dataset_one.json \
  --split test \
  --instance_ids astropy__astropy-12907 \
  --predictions_path ~/cunzhe/swe_runs/swe_lite_official_one/preds.json \
  --max_workers 1 \
  --timeout 1800 \
  --run_id glm_air_astropy12907 \
  --namespace swebench \
  --cache_level env \
  --clean false \
  --report_dir ~/cunzhe/swe_runs/swe_lite_official_one/eval_report
```

CPU placement knobs:

```text
SWE_AGENT_CORE=1          pins the host-side mini-SWE-agent Python process.
SWE_CONTAINER_CPUSET=2    passes --cpuset-cpus=2 to docker run for the sandbox.
```

## Notes

The harness currently uses the mini-SWE-agent runner already present under
`cpu-centric-agentic-ai/mini-swe-agent/`. This folder owns the workload dataset,
case selection, launch policy, and results path. The runner dependency is
explicit so it can later be swapped for OpenHands, SWE-agent, or another local
agent runner.
