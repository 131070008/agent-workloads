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

## Notes

The harness currently uses the mini-SWE-agent runner already present under
`cpu-centric-agentic-ai/mini-swe-agent/`. This folder owns the workload dataset,
case selection, launch policy, and results path. The runner dependency is
explicit so it can later be swapped for OpenHands, SWE-agent, or another local
agent runner.
