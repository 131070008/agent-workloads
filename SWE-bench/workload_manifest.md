# Workload Manifest: SWE-bench

## Goal

Measure agent execution for realistic software engineering tasks: issue
understanding, code exploration, file edits, test execution, and patch
submission.

This is a full agent workload family, unlike BEIR/FAISS retrieval, which is a
sub-workload.

## First Supported Input

- Dataset family: SWE-bench
- Dataset: SWE-bench Lite
- Split: test
- Local cases: 300
- Smoke case: `pallets__flask-4045`
- Local dataset path:
  `workloads/SWE-bench/datasets/swe_bench_lite_smoke`

## Phase Signals To Keep

- LLM calls and per-call latency
- shell/bash command count
- file reads/writes
- test/process execution time
- stdout/stderr observation size
- step count and exit status
- total wall time

## Why It Matters

SWE-style workloads stress the CPU around orchestration rather than raw model
inference alone:

- process creation and command execution
- filesystem traversal and text processing
- sandbox/tool-call boundaries
- test execution and retry loops
- long-running multi-step control flow

## Local Smoke Result

```text
instance: pallets__flask-4045
repo: pallets/flask
status: Submitted
wall time: 925.9s
model: qwen3.6:27b via Ollama
```

Interpretation: even a short standard SWE-bench Lite issue is slow on local
27B-class LLMs, so single-case smoke testing is feasible but batch studies
should use a smaller local model or a cloud/API model.
