# Workload Manifest: WebArena Agent

## Workload Family

- Name: `WebArena`
- Type: web agent benchmark
- Primary upstream: https://github.com/web-arena-x/webarena
- Related runner ecosystem: BrowserGym
- Related dataset/benchmark: Mind2Web

## Why It Is An Agent Bench

WebArena-style workloads require an LLM-backed agent to observe browser state,
choose actions, execute them in a browser environment, and continue until the
task succeeds or fails. This is stronger than a fixed RAG workflow because the
agent controls the sequence of actions.

## Execution Path

```text
task instruction
-> browser environment reset
-> observe page / DOM / accessibility tree / screenshot
-> LLM chooses action
-> browser controller executes click/type/navigate/etc.
-> web app state changes
-> repeat
-> evaluator scores task success
```

## Current Local Status

- Canonical WebArena runner is vendored under `upstream/webarena-src`.
- Local Python 3.10 environment is expected at `.venv-webarena310`.
- Local compatibility requirements live in `requirements-local.txt` because
  upstream `playwright==1.32.1` pins an old `greenlet` that does not build on
  this Mac SDK.
- `run_web_agent.sh` runs a small WebArena example through local
  Ollama/Qwen by default.

Validated local smoke:

```text
config: config_files/examples/2.json
intent: Check out the classification section
mode: llm
model: qwen3:8b
score: 1.0
actions: 2
```

## Next Formal Benchmark Steps

1. Set up the full reproducible WebArena websites or select a standard
   WebArena-compatible task subset.
2. Run more than the local example task, including logged-in site tasks.
3. Use local Ollama/Qwen for path validation and optionally cloud models for
   closer-to-paper comparison.
4. Record E2E time, step count, browser/action latency, LLM latency, and score.

## CPU Signals To Track

- browser startup and per-step action latency
- DOM/accessibility serialization time and size
- screenshot capture and image preprocessing time, if multimodal
- JavaScript/rendering CPU time, when available
- LLM request orchestration latency
- sandbox/process count and memory footprint
